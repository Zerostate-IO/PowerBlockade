from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.routers.auth import get_current_user
from app.template_utils import get_templates

router = APIRouter(tags=["help"])
templates = get_templates()


@router.get("/help", response_class=HTMLResponse)
def help_index(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("help/index.html", {"request": request, "user": user})


@router.get("/help/{topic}", response_class=HTMLResponse)
def help_topic(request: Request, topic: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        f"help/{topic}.html", {"request": request, "user": user, "topic": topic}
    )
