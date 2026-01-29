from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.forward_zone import ForwardZone
from app.models.node import Node
from app.routers.auth import get_current_user
from app.services.config_audit import model_to_dict, record_change
from app.services.forward_zones import write_forward_zones_config
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()


@router.get("/forwardzones", response_class=HTMLResponse)
def forward_zones_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    global_zones = (
        db.query(ForwardZone)
        .filter(ForwardZone.node_id.is_(None))
        .order_by(ForwardZone.domain)
        .all()
    )
    per_node_zones = (
        db.query(ForwardZone)
        .filter(ForwardZone.node_id.isnot(None))
        .order_by(ForwardZone.domain)
        .all()
    )
    nodes = db.query(Node).all()

    return templates.TemplateResponse(
        "forward_zones.html",
        {
            "request": request,
            "user": user,
            "global_zones": global_zones,
            "per_node_zones": per_node_zones,
            "nodes": nodes,
            "message": None,
        },
    )


@router.post("/forwardzones/add")
def forward_zones_add(
    request: Request,
    domain: str = Form(...),
    servers: str = Form(...),
    description: str = Form(""),
    apply_globally: bool = Form(True),
    node_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    node_id_int = None
    if not apply_globally and node_id:
        try:
            node_id_int = int(node_id)
        except ValueError:
            node_id_int = None

    zone = ForwardZone(
        domain=domain.strip().lower().rstrip("."),
        servers=servers.strip(),
        description=description.strip() or None,
        node_id=node_id_int,
    )
    db.add(zone)
    db.flush()
    record_change(
        db,
        entity_type="forward_zone",
        entity_id=zone.id,
        action="create",
        actor_user_id=user.id,
        after_data=model_to_dict(zone, exclude={"node"}),
    )
    db.commit()
    return RedirectResponse(url="/forwardzones", status_code=302)


@router.post("/forwardzones/toggle")
def forward_zones_toggle(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    zone = db.get(ForwardZone, id)
    if zone:
        before = model_to_dict(zone, exclude={"node"})
        zone.enabled = not bool(zone.enabled)
        db.add(zone)
        record_change(
            db,
            entity_type="forward_zone",
            entity_id=zone.id,
            action="toggle",
            actor_user_id=user.id,
            before_data=before,
            after_data=model_to_dict(zone, exclude={"node"}),
        )
        db.commit()
    return RedirectResponse(url="/forwardzones", status_code=302)


@router.post("/forwardzones/delete")
def forward_zones_delete(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    zone = db.get(ForwardZone, id)
    if zone:
        before = model_to_dict(zone, exclude={"node"})
        record_change(
            db,
            entity_type="forward_zone",
            entity_id=zone.id,
            action="delete",
            actor_user_id=user.id,
            before_data=before,
        )
        db.delete(zone)
        db.commit()
    return RedirectResponse(url="/forwardzones", status_code=302)


@router.post("/forwardzones/apply")
def forward_zones_apply(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    global_zones = (
        db.query(ForwardZone)
        .filter(ForwardZone.node_id.is_(None), ForwardZone.enabled.is_(True))
        .order_by(ForwardZone.domain)
        .all()
    )
    per_node_zones = (
        db.query(ForwardZone)
        .filter(ForwardZone.node_id.isnot(None), ForwardZone.enabled.is_(True))
        .order_by(ForwardZone.domain)
        .all()
    )
    nodes = db.query(Node).all()

    write_forward_zones_config(db)
    zone_count = len(global_zones) + len(per_node_zones)

    msg = f"Wrote forward-zones.conf: {zone_count} zones"

    return templates.TemplateResponse(
        "forward_zones.html",
        {
            "request": request,
            "user": user,
            "global_zones": global_zones,
            "per_node_zones": per_node_zones,
            "nodes": nodes,
            "message": msg,
        },
    )
