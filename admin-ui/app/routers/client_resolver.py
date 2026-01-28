from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.client import Client
from app.models.client_resolver_rule import ClientResolverRule
from app.routers.auth import get_current_user
from app.services.ptr_resolver import resolve_client_hostname

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/clients/resolver", response_class=HTMLResponse)
def client_resolver_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rules = db.query(ClientResolverRule).order_by(ClientResolverRule.priority).all()

    return templates.TemplateResponse(
        "client_resolver.html",
        {
            "request": request,
            "user": user,
            "rules": rules,
            "message": None,
        },
    )


@router.post("/clients/resolver/add")
def client_resolver_add(
    request: Request,
    subnet: str = Form(...),
    nameserver: str = Form(...),
    description: str = Form(""),
    priority: int = Form(100),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rule = ClientResolverRule(
        subnet=subnet.strip(),
        nameserver=nameserver.strip(),
        description=description.strip() or None,
        priority=priority,
    )
    db.add(rule)
    db.commit()
    return RedirectResponse(url="/clients/resolver", status_code=302)


@router.post("/clients/resolver/toggle")
def client_resolver_toggle(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rule = db.get(ClientResolverRule, id)
    if rule:
        rule.enabled = not bool(rule.enabled)
        db.add(rule)
        db.commit()
    return RedirectResponse(url="/clients/resolver", status_code=302)


@router.post("/clients/resolver/delete")
def client_resolver_delete(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rule = db.get(ClientResolverRule, id)
    if rule:
        db.delete(rule)
        db.commit()
    return RedirectResponse(url="/clients/resolver", status_code=302)


@router.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    clients = db.query(Client).order_by(Client.last_seen.desc().nullslast()).all()

    return templates.TemplateResponse(
        "clients.html",
        {
            "request": request,
            "user": user,
            "clients": clients,
            "message": None,
        },
    )


@router.post("/clients/set-name")
def clients_set_name(
    request: Request,
    id: int = Form(...),
    display_name: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = db.get(Client, id)
    if client:
        client.display_name = display_name.strip() or None
        db.commit()
    return RedirectResponse(url="/clients", status_code=302)


@router.post("/clients/resolve")
def clients_resolve(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = db.get(Client, id)
    if client:
        resolve_client_hostname(db, client.ip, force=True)
    return RedirectResponse(url="/clients", status_code=302)
