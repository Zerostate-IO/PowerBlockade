"""Advanced Metrics dashboard - full-page Grafana embed for query analytics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.routers.auth import get_current_user
from app.settings import get_settings
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()


@router.get("/analytics/dashboard", response_class=HTMLResponse)
def advanced_metrics(request: Request, db: Session = Depends(get_db)):
    """Full-page Grafana dashboard for query analytics."""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    settings = get_settings()

    # Build the Grafana URL for the Query Analytics dashboard
    grafana_url = settings.grafana_url or "http://grafana:3000"
    # Use kiosk mode for embedded viewing (hides nav and sidebars)
    dashboard_url = (
        f"{grafana_url}/d/powerblockade-analytics/query-analytics?orgId=1&kiosk&theme=dark"
    )

    return templates.TemplateResponse(
        "metrics_dashboard.html",
        {
            "request": request,
            "user": user,
            "dashboard_url": dashboard_url,
        },
    )
