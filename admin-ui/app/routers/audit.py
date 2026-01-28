from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.config_change import ConfigChange
from app.models.user import User
from app.routers.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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
        },
    )
