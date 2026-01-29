from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.template_utils import get_templates

router = APIRouter(tags=["help"])
templates = get_templates()


@router.get("/help", response_class=HTMLResponse)
async def help_index(request: Request):
    return templates.TemplateResponse("help/index.html", {"request": request})


@router.get("/help/{topic}", response_class=HTMLResponse)
async def help_topic(request: Request, topic: str):
    return templates.TemplateResponse(f"help/{topic}.html", {"request": request, "topic": topic})
