from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

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


def format_local_time(
    dt: datetime | None, tz_name: str | None = None, fmt: str = "%Y-%m-%d %H:%M"
) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = timezone.utc

    return dt.astimezone(tz).strftime(fmt)


def csrf_input(request: Request) -> Markup:
    token = getattr(request.state, "csrf_token", "")
    return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')


class PowerBlockadeTemplates(Jinja2Templates):
    """Compatibility wrapper for Starlette's TemplateResponse API drift."""

    def TemplateResponse(self, *args: Any, **kwargs: Any):  # noqa: N802
        if args and isinstance(args[0], Request):
            return super().TemplateResponse(*args, **kwargs)

        if not args or not isinstance(args[0], str):
            return super().TemplateResponse(*args, **kwargs)

        name = args[0]
        context = args[1] if len(args) > 1 else kwargs.pop("context", None)
        if not isinstance(context, dict):
            return super().TemplateResponse(*args, **kwargs)

        request = context.get("request")
        if not isinstance(request, Request):
            raise TypeError("Template context must include a Starlette Request under 'request'")

        if len(args) > 2 and "status_code" not in kwargs:
            kwargs["status_code"] = args[2]
        if len(args) > 3 and "headers" not in kwargs:
            kwargs["headers"] = args[3]
        if len(args) > 4 and "media_type" not in kwargs:
            kwargs["media_type"] = args[4]
        if len(args) > 5 and "background" not in kwargs:
            kwargs["background"] = args[5]
        if len(args) > 6:
            raise TypeError("Too many positional arguments for TemplateResponse")

        return super().TemplateResponse(request, name, context=context, **kwargs)


def get_templates() -> Jinja2Templates:
    from app.settings import get_settings

    settings = get_settings()
    templates = PowerBlockadeTemplates(directory="app/templates")
    templates.env.filters["timeago"] = timeago
    templates.env.filters["format_number"] = format_number
    templates.env.filters["format_local_time"] = format_local_time
    templates.env.globals["csrf_input"] = csrf_input
    templates.env.globals["version"] = settings.pb_version
    return templates
