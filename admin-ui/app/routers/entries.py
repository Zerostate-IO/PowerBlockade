from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.manual_entry import ManualEntry
from app.routers.auth import get_current_user
from app.services.config_audit import model_to_dict, record_change
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()


@router.get("/entries", response_class=HTMLResponse)
def entries_page(
    request: Request,
    type: str | None = None,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    query = db.query(ManualEntry).order_by(ManualEntry.created_at.desc())

    if type in ("allow", "block"):
        query = query.filter(ManualEntry.entry_type == type)

    entries = query.all()

    return templates.TemplateResponse(
        "entries.html",
        {
            "request": request,
            "user": user,
            "entries": entries,
            "filter_type": type,
            "message": None,
        },
    )


@router.post("/entries/delete")
def entries_delete(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    entry = db.query(ManualEntry).filter(ManualEntry.id == id).first()
    if entry:
        before = model_to_dict(entry)
        db.delete(entry)
        record_change(
            db,
            entity_type="manual_entry",
            entity_id=id,
            action="delete",
            actor_user_id=user.id,
            before_data=before,
        )
        db.commit()

    return RedirectResponse(url="/entries", status_code=302)
