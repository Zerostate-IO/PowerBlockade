from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.client import Client
from app.models.dns_query_event import DNSQueryEvent
from app.routers.auth import get_current_user


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def index_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        from app.routers.auth import login_get

        return login_get(request)

    since = datetime.now(timezone.utc) - timedelta(hours=24)

    total = db.scalar(sa.func.count(DNSQueryEvent.id).where(DNSQueryEvent.ts >= since)) or 0
    blocked = (
        db.scalar(
            sa.func.count(DNSQueryEvent.id).where(
                DNSQueryEvent.ts >= since, DNSQueryEvent.blocked.is_(True)
            )
        )
        or 0
    )

    cache_hits = (
        db.scalar(
            sa.func.count(DNSQueryEvent.id).where(
                DNSQueryEvent.ts >= since,
                DNSQueryEvent.blocked.is_(False),
                DNSQueryEvent.latency_ms < 5,
            )
        )
        or 0
    )

    time_saved_total = 0
    if cache_hits > 0:
        avg_latency_miss = (
            db.scalar(
                sa.func.avg(DNSQueryEvent.latency_ms).where(
                    DNSQueryEvent.ts >= since,
                    DNSQueryEvent.blocked.is_(False),
                    DNSQueryEvent.latency_ms >= 5,
                )
            )
            or 0
        )
        avg_latency_hit = (
            db.scalar(
                sa.func.avg(DNSQueryEvent.latency_ms).where(
                    DNSQueryEvent.ts >= since,
                    DNSQueryEvent.blocked.is_(False),
                    DNSQueryEvent.latency_ms < 5,
                )
            )
            or 0
        )
        time_saved_total = (avg_latency_miss - avg_latency_hit) * cache_hits

    hit_rate = cache_hits / total * 100 if total > 0 else 0
    block_rate = blocked / total * 100 if total > 0 else 0

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "total": total,
            "blocked": blocked,
            "hit_rate": hit_rate,
            "time_saved": time_saved_total,
        },
    )
