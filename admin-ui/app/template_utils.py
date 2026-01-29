from __future__ import annotations

from datetime import datetime, timezone

from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.requests import Request


def timeago(dt: datetime | None) -> str:
    if dt is None:
        return "-"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    diff = now - dt
    seconds = diff.total_seconds()

    if seconds < 0:
        return "just now"
    elif seconds < 60:
        return "just now"
    elif seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins} min{'s' if mins != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        return dt.strftime("%Y-%m-%d")


def format_number(value: int | float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def csrf_input(request: Request) -> Markup:
    token = getattr(request.state, "csrf_token", "")
    return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')


def get_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory="app/templates")
    templates.env.filters["timeago"] = timeago
    templates.env.filters["format_number"] = format_number
    templates.env.globals["csrf_input"] = csrf_input
    return templates
