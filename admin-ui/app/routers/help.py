from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["help"])

templates = Jinja2Templates(directory="app/templates")


@router.get("/help", response_class=HTMLResponse)
async def help_index(request: Request):
    return templates.TemplateResponse("help/index.html", {"request": request})


@router.get("/help/{topic}", response_class=HTMLResponse)
async def help_topic(request: Request, topic: str):
    return templates.TemplateResponse(f"help/{topic}.html", {"request": request, "topic": topic})
