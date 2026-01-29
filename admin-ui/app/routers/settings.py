from __future__ import annotations

from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.settings import DEFAULTS, get_setting, set_setting
from app.routers.auth import get_current_user
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()

COMMON_TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Moscow",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Australia/Sydney",
    "Pacific/Auckland",
]


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    current_settings = {}
    for key in DEFAULTS:
        current_settings[key] = get_setting(db, key)

    all_timezones = sorted(available_timezones())

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "settings": current_settings,
            "common_timezones": COMMON_TIMEZONES,
            "all_timezones": all_timezones,
            "message": None,
        },
    )


@router.post("/settings/timezone")
def settings_update_timezone(
    request: Request,
    timezone: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    all_tz = available_timezones()
    if timezone in all_tz:
        set_setting(db, "timezone", timezone)

    return RedirectResponse(url="/settings", status_code=302)


@router.post("/settings/retention")
def settings_update_retention(
    request: Request,
    retention_events_days: int = Form(...),
    retention_rollups_days: int = Form(...),
    retention_node_metrics_days: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if retention_events_days >= 1:
        set_setting(db, "retention_events_days", str(retention_events_days))
    if retention_rollups_days >= 1:
        set_setting(db, "retention_rollups_days", str(retention_rollups_days))
    if retention_node_metrics_days >= 1:
        set_setting(db, "retention_node_metrics_days", str(retention_node_metrics_days))

    return RedirectResponse(url="/settings", status_code=302)
