from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.node import Node
from app.routers.auth import get_current_user
from app.services.node_generator import generate_secondary_package_zip

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/nodes", response_class=HTMLResponse)
def nodes_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    nodes = db.query(Node).order_by(Node.created_at.desc()).all()
    default_primary_url = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        "nodes.html",
        {
            "request": request,
            "user": user,
            "nodes": nodes,
            "default_primary_url": default_primary_url,
            "error": None,
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

    payload = generate_secondary_package_zip(
        node_name=node.name,
        primary_url=primary_url,
        node_api_key=node.api_key,
    )

    filename = f"powerblockade-secondary-{node.name}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
