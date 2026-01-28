from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.dns_query_event import DNSQueryEvent
from app.routers.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


CACHE_HIT_MS_THRESHOLD = 5


@router.get("/precache", response_class=HTMLResponse)
def precache_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    since = datetime.now(timezone.utc) - timedelta(hours=24)

    total = db.scalar(sa.func.count(DNSQueryEvent.id).where(DNSQueryEvent.ts >= since)) or 0

    cache_hits = (
        db.scalar(
            sa.func.count(DNSQueryEvent.id).where(
                DNSQueryEvent.ts >= since,
                DNSQueryEvent.blocked.is_(False),
                DNSQueryEvent.latency_ms < CACHE_HIT_MS_THRESHOLD,
            )
        )
        or 0
    )

    cache_misses = total - cache_hits
    hit_rate = (cache_hits / total * 100) if total > 0 else 0

    avg_latency_hit = (
        db.scalar(
            sa.func.avg(DNSQueryEvent.latency_ms).where(
                DNSQueryEvent.ts >= since,
                DNSQueryEvent.blocked.is_(False),
                DNSQueryEvent.latency_ms < CACHE_HIT_MS_THRESHOLD,
            )
        )
        or 0
    )

    avg_latency_miss = (
        db.scalar(
            sa.func.avg(DNSQueryEvent.latency_ms).where(
                DNSQueryEvent.ts >= since,
                DNSQueryEvent.blocked.is_(False),
                DNSQueryEvent.latency_ms >= CACHE_HIT_MS_THRESHOLD,
            )
        )
        or 0
    )

    time_saved_per_query = avg_latency_miss - avg_latency_hit
    time_saved_total = time_saved_per_query * cache_hits

    top_cached = (
        db.query(DNSQueryEvent.qname, sa.func.count(DNSQueryEvent.id).label("count"))
        .filter(
            DNSQueryEvent.ts >= since,
            DNSQueryEvent.blocked.is_(False),
            DNSQueryEvent.latency_ms < CACHE_HIT_MS_THRESHOLD,
        )
        .group_by(DNSQueryEvent.qname)
        .order_by(sa.desc("count"))
        .limit(10)
        .all()
    )

    return templates.TemplateResponse(
        "precache.html",
        {
            "request": request,
            "user": user,
            "total": total,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "hit_rate": hit_rate,
            "time_saved_total": time_saved_total,
            "time_saved_per_query": time_saved_per_query,
            "top_cached": top_cached,
        },
    )
