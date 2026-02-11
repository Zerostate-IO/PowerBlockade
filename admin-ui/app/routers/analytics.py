from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.blocklist import Blocklist
from app.models.blocklist_entry import BlocklistEntry
from app.models.client import Client
from app.models.dns_query_event import DNSQueryEvent
from app.models.manual_entry import ManualEntry
from app.models.node import Node
from app.models.node_metrics import NodeMetrics
from app.models.settings import get_blocking_state
from app.routers.auth import get_current_user
from app.routers.system import compute_health_warnings, load_health_thresholds
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()

DEFAULT_PAGE_SIZE = 25
QTYPE_NAMES = {
    1: "A",
    2: "NS",
    5: "CNAME",
    6: "SOA",
    12: "PTR",
    15: "MX",
    16: "TXT",
    28: "AAAA",
    33: "SRV",
    65: "HTTPS",
}
RCODE_NAMES = {
    0: "NOERROR",
    1: "FORMERR",
    2: "SERVFAIL",
    3: "NXDOMAIN",
    4: "NOTIMP",
    5: "REFUSED",
}


@router.get("/", response_class=HTMLResponse)
def index_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        from app.routers.auth import login_get

        return login_get(request)

    since = datetime.now(timezone.utc) - timedelta(hours=24)

    total = (
        db.query(sa.func.count(DNSQueryEvent.id)).filter(DNSQueryEvent.ts >= since).scalar() or 0
    )
    blocked = (
        db.query(sa.func.count(DNSQueryEvent.id))
        .filter(DNSQueryEvent.ts >= since, DNSQueryEvent.blocked.is_(True))
        .scalar()
        or 0
    )

    cache_hits = (
        db.query(sa.func.count(DNSQueryEvent.id))
        .filter(
            DNSQueryEvent.ts >= since,
            DNSQueryEvent.blocked.is_(False),
            DNSQueryEvent.latency_ms < 5,
        )
        .scalar()
        or 0
    )

    time_saved_total = 0
    if cache_hits > 0:
        avg_latency_miss = (
            db.query(sa.func.avg(DNSQueryEvent.latency_ms))
            .filter(
                DNSQueryEvent.ts >= since,
                DNSQueryEvent.blocked.is_(False),
                DNSQueryEvent.latency_ms >= 5,
            )
            .scalar()
            or 0
        )
        avg_latency_hit = (
            db.query(sa.func.avg(DNSQueryEvent.latency_ms))
            .filter(
                DNSQueryEvent.ts >= since,
                DNSQueryEvent.blocked.is_(False),
                DNSQueryEvent.latency_ms < 5,
            )
            .scalar()
            or 0
        )
        time_saved_total = (avg_latency_miss - avg_latency_hit) * cache_hits

    nodes = db.query(Node).filter(Node.status == "active").all()
    node_data = []
    total_cache_hits = 0
    total_cache_misses = 0
    for node in nodes:
        latest = (
            db.query(NodeMetrics)
            .filter(NodeMetrics.node_id == node.id)
            .order_by(NodeMetrics.ts.desc())
            .first()
        )
        node_data.append({"node": node, "metrics": latest})
        if latest:
            total_cache_hits += latest.cache_hits
            total_cache_misses += latest.cache_misses

    total_cache_queries = total_cache_hits + total_cache_misses
    real_hit_rate = (total_cache_hits / total_cache_queries * 100) if total_cache_queries > 0 else 0

    thresholds = load_health_thresholds(db)
    warnings = compute_health_warnings(node_data, thresholds)
    critical_count = sum(1 for w in warnings if w.severity == "critical")
    warning_count = sum(1 for w in warnings if w.severity == "warning")

    blocking_state = get_blocking_state(db)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "total": total,
            "blocked": blocked,
            "hit_rate": real_hit_rate,
            "time_saved": time_saved_total,
            "node_count": len(nodes),
            "critical_count": critical_count,
            "warning_count": warning_count,
            "blocking_state": blocking_state,
        },
    )


def _get_client_labels(db: Session, client_ips: set[str]) -> dict[str, str]:
    if not client_ips:
        return {}
    clients = db.query(Client).filter(Client.ip.in_(list(client_ips))).all()
    return {c.ip: c.display_name or c.rdns_name or c.ip for c in clients}


def _get_blocklist_names(db: Session, domains: set[str]) -> dict[str, str]:
    """Look up which blocklist each domain belongs to.

    Returns a dict mapping domain -> blocklist name (or "Manual" for manual entries).
    """
    if not domains:
        return {}

    result: dict[str, str] = {}
    domain_list = list(domains)

    # Normalize domains for lookup (strip trailing dots, lowercase)
    normalized = {d.rstrip(".").lower(): d for d in domain_list}
    normalized_domains = list(normalized.keys())

    # Check blocklist entries first
    entries = (
        db.query(BlocklistEntry.domain, Blocklist.name)
        .join(Blocklist, BlocklistEntry.blocklist_id == Blocklist.id)
        .filter(
            sa.func.lower(BlocklistEntry.domain).in_(normalized_domains),
            Blocklist.enabled.is_(True),
        )
        .all()
    )
    for entry_domain, list_name in entries:
        original = normalized.get(entry_domain.lower())
        if original and original not in result:
            result[original] = list_name

    # Check manual entries for remaining domains
    remaining = [d for d in normalized_domains if normalized.get(d) not in result]
    if remaining:
        manual = (
            db.query(ManualEntry.domain)
            .filter(
                sa.func.lower(ManualEntry.domain).in_(remaining),
                ManualEntry.entry_type == "block",
            )
            .all()
        )
        for (manual_domain,) in manual:
            original = normalized.get(manual_domain.lower())
            if original:
                result[original] = "Manual"

    return result


@router.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request,
    page: int = Query(1, ge=1),
    q: str | None = Query(None),
    client: str | None = Query(None),
    window: TimeWindow = Query("24h"),
    rcode: str | None = Query(None),
    qtype: str | None = Query(None),
    blocked: str | None = Query(None),
    blocklist: str | None = Query(None),
    view: str = Query("all"),
    top_filter: str = Query("all"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    hours = WINDOW_HOURS[window]
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Handle view-based filtering
    if view == "blocked":
        blocked = "yes"
    elif view == "failures":
        # Filter to SERVFAIL and NXDOMAIN
        rcode = None  # Clear rcode filter, we'll handle it below
    elif view == "top":
        query = db.query(
            DNSQueryEvent.qname,
            func.count().label("count"),
            func.sum(func.cast(DNSQueryEvent.blocked, sa.Integer())).label("blocked_count"),
        ).filter(DNSQueryEvent.ts >= since)

        if q:
            query = query.filter(DNSQueryEvent.qname.ilike(f"%{q}%"))
        if client:
            query = query.filter(DNSQueryEvent.client_ip == client)
        if blocklist:
            query = query.filter(DNSQueryEvent.blocklist_name == blocklist)
        if top_filter == "blocked":
            query = query.filter(DNSQueryEvent.blocked.is_(True))
        elif top_filter == "allowed":
            query = query.filter(DNSQueryEvent.blocked.is_(False))

        query = query.group_by(DNSQueryEvent.qname).order_by(func.count().desc())

        total = query.count()
        total_pages = (total + DEFAULT_PAGE_SIZE - 1) // DEFAULT_PAGE_SIZE

        offset = (page - 1) * DEFAULT_PAGE_SIZE
        top_domains = query.offset(offset).limit(DEFAULT_PAGE_SIZE).all()

        # Get distinct blocklist names for dropdown
        blocklist_options = (
            db.query(DNSQueryEvent.blocklist_name)
            .filter(DNSQueryEvent.blocklist_name.isnot(None))
            .distinct()
            .order_by(DNSQueryEvent.blocklist_name)
            .all()
        )
        blocklist_options = [b[0] for b in blocklist_options if b[0]]

        all_clients = (
            db.query(Client.ip, Client.display_name, Client.rdns_name)
            .order_by(Client.display_name, Client.rdns_name, Client.ip)
            .all()
        )
        client_options = [
            {"ip": c.ip, "label": c.display_name or c.rdns_name or c.ip} for c in all_clients
        ]

        return templates.TemplateResponse(
            "logs.html",
            {
                "request": request,
                "user": user,
                "top_domains": top_domains,
                "page": page,
                "total_pages": total_pages,
                "total": total,
                "q": q or "",
                "client": client or "",
                "window": window,
                "blocklist": blocklist or "",
                "view": view,
                "top_filter": top_filter,
                "client_options": client_options,
                "blocklist_options": blocklist_options,
                "window_options": list(WINDOW_HOURS.keys()),
            },
        )

    # Regular log view (all, blocked, failures)
    query = db.query(DNSQueryEvent).filter(DNSQueryEvent.ts >= since)

    if view == "failures":
        query = query.filter(DNSQueryEvent.rcode.in_([2, 3]), DNSQueryEvent.blocked.is_(False))

    if q:
        query = query.filter(DNSQueryEvent.qname.ilike(f"%{q}%"))
    if client:
        query = query.filter(DNSQueryEvent.client_ip == client)
    if rcode:
        rcode_val = next((k for k, v in RCODE_NAMES.items() if v == rcode), None)
        if rcode_val is not None:
            query = query.filter(DNSQueryEvent.rcode == rcode_val)
    if qtype:
        qtype_val = next((k for k, v in QTYPE_NAMES.items() if v == qtype), None)
        if qtype_val is not None:
            query = query.filter(DNSQueryEvent.qtype == qtype_val)
    if blocked == "yes":
        query = query.filter(DNSQueryEvent.blocked.is_(True))
    elif blocked == "no":
        query = query.filter(DNSQueryEvent.blocked.is_(False))
    if blocklist:
        query = query.filter(DNSQueryEvent.blocklist_name == blocklist)

    total = query.count()
    total_pages = (total + DEFAULT_PAGE_SIZE - 1) // DEFAULT_PAGE_SIZE

    offset = (page - 1) * DEFAULT_PAGE_SIZE
    events_raw = (
        query.order_by(DNSQueryEvent.ts.desc()).offset(offset).limit(DEFAULT_PAGE_SIZE).all()
    )

    client_ips = {e.client_ip for e in events_raw}
    labels = _get_client_labels(db, client_ips)

    events = []
    for e in events_raw:
        events.append(
            {
                "ts": e.ts.strftime("%Y-%m-%d %H:%M:%S") if e.ts else "-",
                "client_ip": e.client_ip,
                "client_label": labels.get(e.client_ip, e.client_ip),
                "qname": e.qname,
                "qtype": QTYPE_NAMES.get(e.qtype, str(e.qtype)),
                "rcode": RCODE_NAMES.get(e.rcode, str(e.rcode)),
                "latency_ms": e.latency_ms,
                "blocked": e.blocked,
                "node_name": e.node.name if e.node else "Unknown",
            }
        )

    all_clients = (
        db.query(Client.ip, Client.display_name, Client.rdns_name)
        .order_by(Client.display_name, Client.rdns_name, Client.ip)
        .all()
    )
    client_options = [
        {"ip": c.ip, "label": c.display_name or c.rdns_name or c.ip} for c in all_clients
    ]

    # Get distinct blocklist names for dropdown
    blocklist_options = (
        db.query(DNSQueryEvent.blocklist_name)
        .filter(DNSQueryEvent.blocklist_name.isnot(None))
        .distinct()
        .order_by(DNSQueryEvent.blocklist_name)
        .all()
    )
    blocklist_options = [b[0] for b in blocklist_options if b[0]]

    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "user": user,
            "events": events,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "q": q or "",
            "client": client or "",
            "window": window,
            "rcode": rcode or "",
            "qtype": qtype or "",
            "blocked": blocked or "",
            "blocklist": blocklist or "",
            "view": view,
            "client_options": client_options,
            "rcode_options": list(RCODE_NAMES.values()),
            "qtype_options": list(QTYPE_NAMES.values()),
            "blocklist_options": blocklist_options,
            "window_options": list(WINDOW_HOURS.keys()),
        },
    )


@router.get("/domains", response_class=HTMLResponse)
def domains_page(
    request: Request,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    offset = (page - 1) * DEFAULT_PAGE_SIZE

    domains = (
        db.query(
            DNSQueryEvent.qname,
            func.count().label("count"),
            func.sum(func.cast(DNSQueryEvent.blocked, sa.Integer())).label("blocked"),
        )
        .filter(DNSQueryEvent.ts >= since)
        .group_by(DNSQueryEvent.qname)
        .order_by(func.count().desc())
        .offset(offset)
        .limit(DEFAULT_PAGE_SIZE)
        .all()
    )

    return templates.TemplateResponse(
        "domains.html",
        {"request": request, "user": user, "domains": domains, "page": page},
    )


@router.get("/blocked", response_class=HTMLResponse)
def blocked_page(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return RedirectResponse(url="/logs?view=blocked", status_code=302)


@router.get("/failures", response_class=HTMLResponse)
def failures_page(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return RedirectResponse(url="/logs?view=failures", status_code=302)


TimeWindow = Literal["1h", "6h", "12h", "24h", "3d", "7d"]

WINDOW_HOURS: dict[TimeWindow, int] = {
    "1h": 1,
    "6h": 6,
    "12h": 12,
    "24h": 24,
    "3d": 72,
    "7d": 168,
}


def _get_bucket_minutes(window: TimeWindow) -> int:
    hours = WINDOW_HOURS[window]
    if hours <= 1:
        return 1
    elif hours <= 6:
        return 5
    elif hours <= 24:
        return 15
    elif hours <= 72:
        return 60
    else:
        return 120


@router.get("/api/analytics/history", response_class=JSONResponse)
def analytics_history(
    request: Request,
    window: TimeWindow = Query("24h"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    hours = WINDOW_HOURS[window]
    bucket_minutes = _get_bucket_minutes(window)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    buckets: list[datetime] = []
    current = since.replace(second=0, microsecond=0)
    current = current.replace(minute=(current.minute // bucket_minutes) * bucket_minutes)
    while current <= now:
        buckets.append(current)
        current = current + timedelta(minutes=bucket_minutes)

    sql = sa.text("""
        SELECT
            date_trunc('minute', ts) -
                (EXTRACT(minute FROM ts)::int % :bucket_min) * interval '1 minute' as bucket,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE blocked = true) as blocked,
            COUNT(*) FILTER (WHERE blocked = false AND latency_ms < 5) as cached
        FROM dns_query_events
        WHERE ts >= :since
        GROUP BY bucket
        ORDER BY bucket
    """)

    result = db.execute(sql, {"bucket_min": bucket_minutes, "since": since})
    rows = result.fetchall()

    stats_by_bucket: dict[datetime, dict] = {}
    for row in rows:
        bucket_ts = row[0]
        if bucket_ts and bucket_ts.tzinfo is None:
            bucket_ts = bucket_ts.replace(tzinfo=timezone.utc)
        stats_by_bucket[bucket_ts] = {
            "total": row[1] or 0,
            "blocked": row[2] or 0,
            "cached": row[3] or 0,
        }

    labels: list[str] = []
    total_series: list[int] = []
    blocked_series: list[int] = []
    cached_series: list[int] = []

    for bucket in buckets:
        if hours <= 24:
            label = bucket.strftime("%H:%M")
        else:
            label = bucket.strftime("%m/%d %H:%M")
        labels.append(label)

        stats = stats_by_bucket.get(bucket, {"total": 0, "blocked": 0, "cached": 0})
        total_series.append(stats["total"])
        blocked_series.append(stats["blocked"])
        cached_series.append(stats["cached"])

    return JSONResponse(
        {
            "labels": labels,
            "series": {
                "total": total_series,
                "blocked": blocked_series,
                "cached": cached_series,
            },
            "window": window,
        }
    )
