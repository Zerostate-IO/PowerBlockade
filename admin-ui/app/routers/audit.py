from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.blocklist import Blocklist
from app.models.config_change import ConfigChange
from app.models.forward_zone import ForwardZone
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.config_audit import model_to_dict, record_change
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()

ROLLBACK_SUPPORTED_TYPES = {"blocklist", "forward_zone"}


@router.get("/audit", response_class=HTMLResponse)
def audit_page(
    request: Request,
    entity_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    page_size = 50
    offset = (page - 1) * page_size

    query = db.query(ConfigChange)
    if entity_type:
        query = query.filter(ConfigChange.entity_type == entity_type)
    query = query.order_by(ConfigChange.created_at.desc())

    total = query.count()
    changes = query.offset(offset).limit(page_size).all()

    user_ids = {c.actor_user_id for c in changes if c.actor_user_id}
    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(list(user_ids))).all()
        users_map = {u.id: u.username for u in users}

    entity_types = (
        db.query(ConfigChange.entity_type).distinct().order_by(ConfigChange.entity_type).all()
    )
    entity_types = [e[0] for e in entity_types]

    total_pages = (total + page_size - 1) // page_size

    return templates.TemplateResponse(
        "audit.html",
        {
            "request": request,
            "user": user,
            "changes": changes,
            "users_map": users_map,
            "entity_types": entity_types,
            "current_type": entity_type,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "rollback_types": ROLLBACK_SUPPORTED_TYPES,
            "rollback_message": request.query_params.get("rollback"),
        },
    )


@router.post("/audit/rollback")
def rollback_change(
    request: Request,
    change_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    change = db.get(ConfigChange, change_id)
    if not change:
        return RedirectResponse(url="/audit?rollback=Change+not+found", status_code=302)

    if change.entity_type not in ROLLBACK_SUPPORTED_TYPES:
        return RedirectResponse(
            url=f"/audit?rollback=Rollback+not+supported+for+{change.entity_type}", status_code=302
        )

    if change.action == "delete" and change.before_data:
        result = _rollback_delete(db, change, user.id)
    elif change.action in ("create", "toggle", "update", "update_frequency") and change.before_data:
        result = _rollback_update(db, change, user.id)
    elif change.action == "create" and not change.before_data and change.entity_id:
        result = _rollback_create(db, change, user.id)
    else:
        result = "Cannot rollback this change type"

    return RedirectResponse(url=f"/audit?rollback={result.replace(' ', '+')}", status_code=302)


def _rollback_delete(db: Session, change: ConfigChange, user_id: int) -> str:
    data = change.before_data
    if not data:
        return "No before_data to restore"

    if change.entity_type == "blocklist":
        existing = db.query(Blocklist).filter(Blocklist.url == data.get("url")).first()
        if existing:
            return f"Blocklist with URL already exists (id={existing.id})"
        b = Blocklist(
            name=data.get("name", ""),
            url=data.get("url", ""),
            format=data.get("format", "domains"),
            list_type=data.get("list_type", "block"),
            enabled=data.get("enabled", True),
            update_frequency_hours=data.get("update_frequency_hours", 24),
        )
        db.add(b)
        db.flush()
        record_change(
            db,
            entity_type="blocklist",
            entity_id=b.id,
            action="rollback_restore",
            actor_user_id=user_id,
            after_data=model_to_dict(b),
            comment=f"Rolled back delete from change #{change.id}",
        )
        db.commit()
        return f"Restored blocklist: {b.name}"

    elif change.entity_type == "forward_zone":
        existing = db.query(ForwardZone).filter(ForwardZone.domain == data.get("domain")).first()
        if existing:
            return f"Forward zone for domain already exists (id={existing.id})"
        fz = ForwardZone(
            domain=data.get("domain", ""),
            servers=data.get("servers", ""),
            description=data.get("description"),
            enabled=data.get("enabled", True),
            node_id=data.get("node_id"),
        )
        db.add(fz)
        db.flush()
        record_change(
            db,
            entity_type="forward_zone",
            entity_id=fz.id,
            action="rollback_restore",
            actor_user_id=user_id,
            after_data=model_to_dict(fz),
            comment=f"Rolled back delete from change #{change.id}",
        )
        db.commit()
        return f"Restored forward zone: {fz.domain}"

    return "Unsupported entity type"


def _rollback_update(db: Session, change: ConfigChange, user_id: int) -> str:
    data = change.before_data
    if not data or not change.entity_id:
        return "No before_data or entity_id"

    if change.entity_type == "blocklist":
        b = db.get(Blocklist, change.entity_id)
        if not b:
            return f"Blocklist #{change.entity_id} not found"
        before = model_to_dict(b)
        b.name = data.get("name", b.name)
        b.enabled = data.get("enabled", b.enabled)
        b.update_frequency_hours = data.get("update_frequency_hours", b.update_frequency_hours)
        db.add(b)
        record_change(
            db,
            entity_type="blocklist",
            entity_id=b.id,
            action="rollback_update",
            actor_user_id=user_id,
            before_data=before,
            after_data=model_to_dict(b),
            comment=f"Rolled back change #{change.id}",
        )
        db.commit()
        return f"Rolled back blocklist: {b.name}"

    elif change.entity_type == "forward_zone":
        fz = db.get(ForwardZone, change.entity_id)
        if not fz:
            return f"Forward zone #{change.entity_id} not found"
        before = model_to_dict(fz)
        fz.domain = data.get("domain", fz.domain)
        fz.servers = data.get("servers", fz.servers)
        fz.description = data.get("description", fz.description)
        fz.enabled = data.get("enabled", fz.enabled)
        db.add(fz)
        record_change(
            db,
            entity_type="forward_zone",
            entity_id=fz.id,
            action="rollback_update",
            actor_user_id=user_id,
            before_data=before,
            after_data=model_to_dict(fz),
            comment=f"Rolled back change #{change.id}",
        )
        db.commit()
        return f"Rolled back forward zone: {fz.domain}"

    return "Unsupported entity type"


def _rollback_create(db: Session, change: ConfigChange, user_id: int) -> str:
    if not change.entity_id:
        return "No entity_id"

    if change.entity_type == "blocklist":
        b = db.get(Blocklist, change.entity_id)
        if not b:
            return f"Blocklist #{change.entity_id} already deleted"
        before = model_to_dict(b)
        record_change(
            db,
            entity_type="blocklist",
            entity_id=b.id,
            action="rollback_delete",
            actor_user_id=user_id,
            before_data=before,
            comment=f"Rolled back create from change #{change.id}",
        )
        db.delete(b)
        db.commit()
        return f"Deleted blocklist: {before.get('name', 'unknown')}"

    elif change.entity_type == "forward_zone":
        fz = db.get(ForwardZone, change.entity_id)
        if not fz:
            return f"Forward zone #{change.entity_id} already deleted"
        before = model_to_dict(fz)
        record_change(
            db,
            entity_type="forward_zone",
            entity_id=fz.id,
            action="rollback_delete",
            actor_user_id=user_id,
            before_data=before,
            comment=f"Rolled back create from change #{change.id}",
        )
        db.delete(fz)
        db.commit()
        return f"Deleted forward zone: {before.get('domain', 'unknown')}"

    return "Unsupported entity type"
