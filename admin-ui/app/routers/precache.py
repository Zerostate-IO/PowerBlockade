from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.dns_query_event import DNSQueryEvent
from app.models.settings import (
    get_precache_custom_refresh_minutes,
    get_precache_domain_count,
    get_precache_enabled,
    get_precache_ignore_ttl,
    get_precache_refresh_minutes,
    set_setting,
)
from app.routers.auth import get_current_user
from app.services.precache import (
    get_precache_stats,
    get_top_domains_to_warm,
    warm_cache,
)
from app.settings import get_settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/precache", response_class=HTMLResponse)
def precache_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    settings = get_settings()
    threshold = settings.cache_hit_threshold_ms
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    total = (
        db.query(sa.func.count(DNSQueryEvent.id)).filter(DNSQueryEvent.ts >= since).scalar() or 0
    )

    cache_hits = (
        db.query(sa.func.count(DNSQueryEvent.id))
        .filter(
            DNSQueryEvent.ts >= since,
            DNSQueryEvent.blocked.is_(False),
            DNSQueryEvent.latency_ms < threshold,
        )
        .scalar()
        or 0
    )

    cache_misses = total - cache_hits
    hit_rate = (cache_hits / total * 100) if total > 0 else 0

    avg_latency_hit = (
        db.query(sa.func.avg(DNSQueryEvent.latency_ms))
        .filter(
            DNSQueryEvent.ts >= since,
            DNSQueryEvent.blocked.is_(False),
            DNSQueryEvent.latency_ms < threshold,
        )
        .scalar()
        or 0
    )

    avg_latency_miss = (
        db.query(sa.func.avg(DNSQueryEvent.latency_ms))
        .filter(
            DNSQueryEvent.ts >= since,
            DNSQueryEvent.blocked.is_(False),
            DNSQueryEvent.latency_ms >= threshold,
        )
        .scalar()
        or 0
    )

    time_saved_per_query = avg_latency_miss - avg_latency_hit
    time_saved_total = time_saved_per_query * cache_hits

    top_cached = (
        db.query(DNSQueryEvent.qname, sa.func.count(DNSQueryEvent.id).label("count"))
        .filter(
            DNSQueryEvent.ts >= since,
            DNSQueryEvent.blocked.is_(False),
            DNSQueryEvent.latency_ms < threshold,
        )
        .group_by(DNSQueryEvent.qname)
        .order_by(sa.desc("count"))
        .limit(10)
        .all()
    )

    precache_enabled = get_precache_enabled(db)
    domain_count = get_precache_domain_count(db)
    refresh_minutes = get_precache_refresh_minutes(db)
    ignore_ttl = get_precache_ignore_ttl(db)
    custom_refresh = get_precache_custom_refresh_minutes(db)

    warmable_domains = get_top_domains_to_warm(db, hours=24, limit=domain_count)
    precache_stats = get_precache_stats()

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
            "warmable_count": len(warmable_domains),
            "warming_message": request.query_params.get("warmed"),
            "precache_enabled": precache_enabled,
            "domain_count": domain_count,
            "refresh_minutes": refresh_minutes,
            "ignore_ttl": ignore_ttl,
            "custom_refresh": custom_refresh,
            "precache_stats": precache_stats,
        },
    )


def _warm_cache_background(domains: list[str], dns_server: str, port: int) -> None:
    warm_cache(domains, dns_server, port)


@router.post("/precache/warm")
def trigger_warm_cache(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    settings = get_settings()
    recursor_url = settings.recursor_api_url or "http://recursor:8082"
    dns_host = recursor_url.replace("http://", "").replace("https://", "").split(":")[0]
    if dns_host in ("recursor", "localhost"):
        dns_host = "127.0.0.1"

    domain_count = get_precache_domain_count(db)
    domains = get_top_domains_to_warm(db, hours=24, limit=domain_count)

    if domains:
        background_tasks.add_task(_warm_cache_background, domains, dns_host, 53)
        msg = f"Warming {len(domains)} domains"
    else:
        msg = "No domains to warm"

    return RedirectResponse(url=f"/precache?warmed={msg}", status_code=302)


@router.post("/precache/settings")
def update_precache_settings(
    request: Request,
    db: Session = Depends(get_db),
    enabled: str = Form("false"),
    domain_count: int = Form(1000),
    refresh_minutes: int = Form(30),
    ignore_ttl: str = Form("false"),
    custom_refresh: int = Form(60),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    domain_count = max(100, min(100000, domain_count))
    refresh_minutes = max(5, min(1440, refresh_minutes))
    custom_refresh = max(5, min(1440, custom_refresh))

    set_setting(db, "precache_enabled", "true" if enabled == "true" else "false")
    set_setting(db, "precache_domain_count", str(domain_count))
    set_setting(db, "precache_refresh_minutes", str(refresh_minutes))
    set_setting(db, "precache_ignore_ttl", "true" if ignore_ttl == "true" else "false")
    set_setting(db, "precache_custom_refresh_minutes", str(custom_refresh))

    return RedirectResponse(url="/precache?warmed=Settings+saved", status_code=302)
