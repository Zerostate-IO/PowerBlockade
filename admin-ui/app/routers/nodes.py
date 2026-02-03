from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.dns_query_event import DNSQueryEvent
from app.models.node import Node
from app.models.node_metrics import NodeMetrics
from app.routers.auth import get_current_user
from app.services.node_generator import generate_secondary_package_zip
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()

STALE_THRESHOLD_MINUTES = 5


def get_node_status_badge(node: Node) -> tuple[str, str]:
    if node.status == "error" or node.last_error:
        return ("bg-red-900/50 text-red-400", "error")

    if node.last_seen is None:
        return ("bg-slate-700/50 text-slate-400", "pending")

    last_seen: datetime = node.last_seen  # type: ignore[assignment]
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=STALE_THRESHOLD_MINUTES)

    if last_seen < stale_cutoff:
        return ("bg-amber-900/50 text-amber-400", "stale")

    return ("bg-emerald-900/50 text-emerald-400", "active")


def get_latest_metrics(db: Session, node_id: int) -> NodeMetrics | None:
    return (
        db.query(NodeMetrics)
        .filter(NodeMetrics.node_id == node_id)
        .order_by(NodeMetrics.ts.desc())
        .first()
    )


def compute_cache_hit_rate(metrics: NodeMetrics | None) -> float | None:
    if metrics is None:
        return None
    total = metrics.cache_hits + metrics.cache_misses
    if total == 0:
        return None
    return (metrics.cache_hits / total) * 100


def get_node_query_stats(db: Session) -> dict[int, tuple[int, int]]:
    stats = (
        db.query(
            DNSQueryEvent.node_id,
            func.count(DNSQueryEvent.id).label("total"),
            func.count().filter(DNSQueryEvent.blocked == True).label("blocked"),
        )
        .filter(DNSQueryEvent.node_id.isnot(None))
        .group_by(DNSQueryEvent.node_id)
        .all()
    )
    return {row.node_id: (row.total, int(row.blocked or 0)) for row in stats}


ERROR_MESSAGES = {
    "cannot_delete_primary": "Cannot delete the primary node.",
}


@router.get("/nodes", response_class=HTMLResponse)
def nodes_page(request: Request, error: str | None = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    nodes = db.query(Node).order_by(Node.created_at.desc()).all()
    query_stats = get_node_query_stats(db)

    node_data = []
    for node in nodes:
        metrics = get_latest_metrics(db, node.id)
        cache_hit_rate = compute_cache_hit_rate(metrics)
        status_class, status_text = get_node_status_badge(node)
        total, blocked = query_stats.get(node.id, (0, 0))
        node_data.append(
            {
                "node": node,
                "status_class": status_class,
                "status_text": status_text,
                "cache_hit_rate": cache_hit_rate,
                "is_primary": node.name == "primary",
                "queries_total": total,
                "queries_blocked": blocked,
            }
        )

    default_primary_url = str(request.base_url).rstrip("/")
    error_message = ERROR_MESSAGES.get(error) if error else None
    return templates.TemplateResponse(
        "nodes.html",
        {
            "request": request,
            "user": user,
            "node_data": node_data,
            "default_primary_url": default_primary_url,
            "error": error_message,
        },
    )


@router.post("/nodes/generate")
def nodes_generate(
    request: Request,
    name: str = Form(...),
    primary_url: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    node_name = name.strip()
    if not node_name:
        return RedirectResponse(url="/nodes", status_code=302)

    node = db.query(Node).filter(Node.name == node_name).one_or_none()
    if node is None:
        api_key = secrets.token_urlsafe(48)[:64]
        node = Node(name=node_name, api_key=api_key)
        db.add(node)
        db.commit()
        db.refresh(node)

    recursor_api_key = secrets.token_urlsafe(32)
    payload = generate_secondary_package_zip(
        node_name=node.name,
        primary_url=primary_url,
        node_api_key=node.api_key,
        recursor_api_key=recursor_api_key,
    )

    filename = f"powerblockade-secondary-{node.name}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/nodes/delete")
def nodes_delete(
    request: Request,
    node_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    node = db.query(Node).filter(Node.id == node_id).one_or_none()
    if node is None:
        return RedirectResponse(url="/nodes", status_code=302)

    if node.name == "primary":
        return RedirectResponse(url="/nodes?error=cannot_delete_primary", status_code=302)

    db.delete(node)
    db.commit()
    return RedirectResponse(url="/nodes", status_code=302)


@router.post("/nodes/force-sync")
def nodes_force_sync(
    request: Request,
    node_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    node = db.query(Node).filter(Node.id == node_id).one_or_none()
    if node is None:
        return RedirectResponse(url="/nodes", status_code=302)

    node.config_version += 1
    node.last_error = None
    db.commit()
    return RedirectResponse(url="/nodes", status_code=302)


@router.post("/nodes/clear-error")
def nodes_clear_error(
    request: Request,
    node_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    node = db.query(Node).filter(Node.id == node_id).one_or_none()
    if node is None:
        return RedirectResponse(url="/nodes", status_code=302)

    node.last_error = None
    if node.status == "error":
        node.status = "active"
    db.commit()
    return RedirectResponse(url="/nodes", status_code=302)
