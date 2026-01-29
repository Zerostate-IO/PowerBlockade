from __future__ import annotations

import ipaddress
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.client import Client
from app.models.client_group import ClientGroup
from app.routers.auth import get_current_user
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()
log = logging.getLogger(__name__)

COLORS = [
    "slate",
    "red",
    "orange",
    "amber",
    "yellow",
    "lime",
    "green",
    "emerald",
    "teal",
    "cyan",
    "sky",
    "blue",
    "indigo",
    "violet",
    "purple",
    "fuchsia",
    "pink",
    "rose",
]


def _ip_in_cidr(ip: str, cidr: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


@router.get("/clients/groups", response_class=HTMLResponse)
def groups_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    groups = db.query(ClientGroup).order_by(ClientGroup.name).all()

    group_stats = {}
    for g in groups:
        client_count = db.query(func.count(Client.id)).filter(Client.group_id == g.id).scalar() or 0
        group_stats[g.id] = {"client_count": client_count}

    ungrouped_count = (
        db.query(func.count(Client.id)).filter(Client.group_id.is_(None)).scalar() or 0
    )

    return templates.TemplateResponse(
        "client_groups.html",
        {
            "request": request,
            "user": user,
            "groups": groups,
            "group_stats": group_stats,
            "ungrouped_count": ungrouped_count,
            "colors": COLORS,
        },
    )


@router.post("/clients/groups/create")
def create_group(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    cidr: str = Form(""),
    color: str = Form("slate"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    existing = db.query(ClientGroup).filter(ClientGroup.name == name).first()
    if existing:
        return RedirectResponse(url="/clients/groups?error=name_exists", status_code=302)

    if cidr:
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            return RedirectResponse(url="/clients/groups?error=invalid_cidr", status_code=302)

    group = ClientGroup(
        name=name,
        description=description or None,
        cidr=cidr or None,
        color=color if color in COLORS else "slate",
    )
    db.add(group)
    db.commit()

    if cidr:
        _auto_assign_by_cidr(db, group)

    return RedirectResponse(url="/clients/groups", status_code=302)


@router.post("/clients/groups/delete")
def delete_group(
    request: Request,
    group_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    group = db.get(ClientGroup, group_id)
    if group:
        db.query(Client).filter(Client.group_id == group_id).update({"group_id": None})
        db.delete(group)
        db.commit()

    return RedirectResponse(url="/clients/groups", status_code=302)


@router.post("/clients/groups/update")
def update_group(
    request: Request,
    group_id: int = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    cidr: str = Form(""),
    color: str = Form("slate"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    group = db.get(ClientGroup, group_id)
    if not group:
        return RedirectResponse(url="/clients/groups", status_code=302)

    existing = (
        db.query(ClientGroup).filter(ClientGroup.name == name, ClientGroup.id != group_id).first()
    )
    if existing:
        return RedirectResponse(url="/clients/groups?error=name_exists", status_code=302)

    if cidr:
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            return RedirectResponse(url="/clients/groups?error=invalid_cidr", status_code=302)

    group.name = name
    group.description = description or None
    old_cidr = group.cidr
    group.cidr = cidr or None
    group.color = color if color in COLORS else "slate"
    db.commit()

    if cidr and cidr != old_cidr:
        _auto_assign_by_cidr(db, group)

    return RedirectResponse(url="/clients/groups", status_code=302)


@router.post("/clients/groups/auto-assign")
def auto_assign_groups(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    groups = db.query(ClientGroup).filter(ClientGroup.cidr.isnot(None)).all()
    assigned = 0

    for group in groups:
        assigned += _auto_assign_by_cidr(db, group)

    return RedirectResponse(url=f"/clients/groups?assigned={assigned}", status_code=302)


def _auto_assign_by_cidr(db: Session, group: ClientGroup) -> int:
    if not group.cidr:
        return 0

    clients = db.query(Client).filter(Client.group_id.is_(None)).all()
    assigned = 0

    for client in clients:
        if _ip_in_cidr(client.ip, group.cidr):
            client.group_id = group.id
            assigned += 1

    if assigned > 0:
        db.commit()

    return assigned


@router.post("/clients/set-group")
def set_client_group(
    request: Request,
    client_id: int = Form(...),
    group_id: int = Form(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = db.get(Client, client_id)
    if client:
        client.group_id = group_id if group_id and group_id > 0 else None
        db.commit()

    return RedirectResponse(url="/clients", status_code=302)
