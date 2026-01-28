from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.node import Node
from app.models.node_metrics import NodeMetrics
from app.routers.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/system", response_class=HTMLResponse)
def system_health(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    nodes = db.query(Node).filter(Node.status == "active").all()

    node_data = []
    for node in nodes:
        latest = (
            db.query(NodeMetrics)
            .filter(NodeMetrics.node_id == node.id)
            .order_by(NodeMetrics.ts.desc())
            .first()
        )
        node_data.append({"node": node, "metrics": latest})

    return templates.TemplateResponse(
        "system.html",
        {
            "request": request,
            "user": user,
            "nodes": node_data,
        },
    )
