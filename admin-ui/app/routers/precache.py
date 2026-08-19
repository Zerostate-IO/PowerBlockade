from __future__ import annotations

from datetime import datetime, timedelta, timezone

import dns.rdatatype
import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.dns_query_event import DNSQueryEvent
from app.models.settings import (
    get_precache_boot_burst_concurrency,
    get_precache_boot_burst_enabled,
    get_precache_boot_burst_qps,
    get_precache_custom_refresh_minutes,
    get_precache_dns_port,
    get_precache_dns_server,
    get_precache_domain_count,
    get_precache_enabled,
    get_precache_ignore_ttl,
    get_precache_max_queries_per_pass,
    get_precache_refresh_minutes,
    set_setting,
)
from app.routers.auth import get_current_user
from app.services.boot_burst import get_last_boot_burst
from app.services.precache import (
    get_precache_stats,
    get_top_pairs_to_warm,
    warm_cache,
)
from app.settings import get_settings
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()


@router.get("/precache", response_class=HTMLResponse)
def precache_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    settings = get_settings()
    threshold = settings.cache_hit_threshold_ms
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    total = (
        db.query(sa.func.count(DNSQueryEvent.id))
        .filter(DNSQueryEvent.ts >= since, DNSQueryEvent.is_internal.is_(False))
        .scalar()
        or 0
    )

    cache_hits = (
        db.query(sa.func.count(DNSQueryEvent.id))
        .filter(
            DNSQueryEvent.ts >= since,
            DNSQueryEvent.blocked.is_(False),
            DNSQueryEvent.latency_ms < threshold,
            DNSQueryEvent.is_internal.is_(False),
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
            DNSQueryEvent.is_internal.is_(False),
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
            DNSQueryEvent.is_internal.is_(False),
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
            DNSQueryEvent.is_internal.is_(False),
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
    dns_server = get_precache_dns_server(db)
    dns_port = get_precache_dns_port(db)
    max_queries_per_pass = get_precache_max_queries_per_pass(db)
    boot_burst_enabled = get_precache_boot_burst_enabled(db)
    boot_burst_concurrency = get_precache_boot_burst_concurrency(db)
    boot_burst_qps = get_precache_boot_burst_qps(db)
    boot_burst_summary = get_last_boot_burst()

    warmable_pairs = get_top_pairs_to_warm(db, hours=24, limit=domain_count)
    precache_stats = get_precache_stats()
    qtype_counts = sorted(precache_stats.get("by_qtype", {}).items(), key=lambda kv: -kv[1])[:5]
    qtype_counts = [(dns.rdatatype.to_text(qtype), count) for qtype, count in qtype_counts]

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
            "warmable_count": len(warmable_pairs),
            "qtype_counts": qtype_counts,
            "warming_message": request.query_params.get("warmed"),
            "precache_enabled": precache_enabled,
            "domain_count": domain_count,
            "refresh_minutes": refresh_minutes,
            "ignore_ttl": ignore_ttl,
            "custom_refresh": custom_refresh,
            "dns_server": dns_server,
            "dns_port": dns_port,
            "max_queries_per_pass": max_queries_per_pass,
            "precache_stats": precache_stats,
            "boot_burst_enabled": boot_burst_enabled,
            "boot_burst_concurrency": boot_burst_concurrency,
            "boot_burst_qps": boot_burst_qps,
            "boot_burst_summary": boot_burst_summary,
        },
    )


@router.get("/precache/boot-burst")
def boot_burst_status(request: Request, db: Session = Depends(get_db)):
    """Structured summary of the last boot warm burst (JSON, auth-gated).

    Returns the in-memory result recorded by the last startup burst:
    status, sent/succeeded/failed/skipped counters, duration and top
    failures. A burst that had failures is reported as ``partial`` or
    ``failed`` -- never silently declared warm.
    """
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return get_last_boot_burst() or {
        "status": "never-run",
        "reason": "no boot burst has run since admin-ui startup",
    }


def _warm_cache_background(pairs: list[tuple[str, int]], dns_server: str, port: int) -> None:
    warm_cache(pairs, dns_server, port)


@router.post("/precache/warm")
def trigger_warm_cache(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    dns_host = get_precache_dns_server(db)
    dns_port = get_precache_dns_port(db)
    domain_count = get_precache_domain_count(db)
    max_queries = get_precache_max_queries_per_pass(db)
    pairs = get_top_pairs_to_warm(db, hours=24, limit=domain_count, max_queries=max_queries)

    if pairs:
        background_tasks.add_task(_warm_cache_background, pairs, dns_host, dns_port)
        msg = f"Warming {len(pairs)} (name, type) pairs"
    else:
        msg = "No pairs to warm"

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
    dns_server: str = Form("dnsdist"),
    max_queries_per_pass: int = Form(2000),
    boot_burst_enabled: str = Form("false"),
    boot_burst_concurrency: int = Form(8),
    boot_burst_qps: float = Form(50.0),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    domain_count = max(100, min(100000, domain_count))
    refresh_minutes = max(5, min(1440, refresh_minutes))
    custom_refresh = max(5, min(1440, custom_refresh))
    max_queries_per_pass = max(100, min(100000, max_queries_per_pass))
    dns_server = dns_server.strip() or "dnsdist"
    # Same clamps as the settings getters, so a saved value can never be
    # read back differently than it was written.
    boot_burst_concurrency = max(1, min(64, boot_burst_concurrency))
    boot_burst_qps = max(1.0, min(1000.0, boot_burst_qps))

    set_setting(db, "precache_enabled", "true" if enabled == "true" else "false")
    set_setting(db, "precache_domain_count", str(domain_count))
    set_setting(db, "precache_refresh_minutes", str(refresh_minutes))
    set_setting(db, "precache_ignore_ttl", "true" if ignore_ttl == "true" else "false")
    set_setting(db, "precache_custom_refresh_minutes", str(custom_refresh))
    set_setting(db, "precache_dns_server", dns_server)
    set_setting(db, "precache_max_queries_per_pass", str(max_queries_per_pass))
    set_setting(db, "precache_boot_burst_enabled", "true" if boot_burst_enabled == "true" else "false")
    set_setting(db, "precache_boot_burst_concurrency", str(boot_burst_concurrency))
    set_setting(db, "precache_boot_burst_qps", str(boot_burst_qps))

    return RedirectResponse(url="/precache?warmed=Settings+saved", status_code=302)
