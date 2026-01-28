from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.dns_query_event import DNSQueryEvent
from app.models.query_rollup import QueryRollup

log = logging.getLogger(__name__)

CACHE_HIT_LATENCY_THRESHOLD_MS = 5


def compute_hourly_rollup(db: Session, hour_start: datetime) -> int:
    hour_end = hour_start + timedelta(hours=1)

    results = (
        db.query(
            DNSQueryEvent.client_id,
            DNSQueryEvent.node_id,
            func.count().label("total"),
            func.sum(func.cast(DNSQueryEvent.blocked, sa.Integer())).label("blocked"),
            func.sum(func.case((DNSQueryEvent.rcode == 3, 1), else_=0)).label("nxdomain"),
            func.sum(func.case((DNSQueryEvent.rcode == 2, 1), else_=0)).label("servfail"),
            func.sum(
                func.case(
                    (DNSQueryEvent.latency_ms < CACHE_HIT_LATENCY_THRESHOLD_MS, 1),
                    else_=0,
                )
            ).label("cache_hits"),
            func.avg(DNSQueryEvent.latency_ms).label("avg_latency"),
            func.count(func.distinct(DNSQueryEvent.qname)).label("unique_domains"),
        )
        .filter(DNSQueryEvent.ts >= hour_start, DNSQueryEvent.ts < hour_end)
        .group_by(DNSQueryEvent.client_id, DNSQueryEvent.node_id)
        .all()
    )

    count = 0
    for row in results:
        existing = (
            db.query(QueryRollup)
            .filter(
                QueryRollup.bucket_start == hour_start,
                QueryRollup.granularity == "hourly",
                QueryRollup.client_id == row.client_id,
                QueryRollup.node_id == row.node_id,
            )
            .one_or_none()
        )

        if existing:
            existing.total_queries = row.total or 0
            existing.blocked_queries = int(row.blocked or 0)
            existing.nxdomain_count = row.nxdomain or 0
            existing.servfail_count = row.servfail or 0
            existing.cache_hits = row.cache_hits or 0
            existing.avg_latency_ms = int(row.avg_latency) if row.avg_latency else None
            existing.unique_domains = row.unique_domains or 0
        else:
            rollup = QueryRollup(
                bucket_start=hour_start,
                granularity="hourly",
                client_id=row.client_id,
                node_id=row.node_id,
                total_queries=row.total or 0,
                blocked_queries=int(row.blocked or 0),
                nxdomain_count=row.nxdomain or 0,
                servfail_count=row.servfail or 0,
                cache_hits=row.cache_hits or 0,
                avg_latency_ms=int(row.avg_latency) if row.avg_latency else None,
                unique_domains=row.unique_domains or 0,
            )
            db.add(rollup)
        count += 1

    db.commit()
    return count


def compute_daily_rollup(db: Session, day_start: datetime) -> int:
    day_end = day_start + timedelta(days=1)

    results = (
        db.query(
            QueryRollup.client_id,
            QueryRollup.node_id,
            func.sum(QueryRollup.total_queries).label("total"),
            func.sum(QueryRollup.blocked_queries).label("blocked"),
            func.sum(QueryRollup.nxdomain_count).label("nxdomain"),
            func.sum(QueryRollup.servfail_count).label("servfail"),
            func.sum(QueryRollup.cache_hits).label("cache_hits"),
            func.avg(QueryRollup.avg_latency_ms).label("avg_latency"),
            func.sum(QueryRollup.unique_domains).label("unique_domains"),
        )
        .filter(
            QueryRollup.bucket_start >= day_start,
            QueryRollup.bucket_start < day_end,
            QueryRollup.granularity == "hourly",
        )
        .group_by(QueryRollup.client_id, QueryRollup.node_id)
        .all()
    )

    count = 0
    for row in results:
        existing = (
            db.query(QueryRollup)
            .filter(
                QueryRollup.bucket_start == day_start,
                QueryRollup.granularity == "daily",
                QueryRollup.client_id == row.client_id,
                QueryRollup.node_id == row.node_id,
            )
            .one_or_none()
        )

        if existing:
            existing.total_queries = row.total or 0
            existing.blocked_queries = row.blocked or 0
            existing.nxdomain_count = row.nxdomain or 0
            existing.servfail_count = row.servfail or 0
            existing.cache_hits = row.cache_hits or 0
            existing.avg_latency_ms = int(row.avg_latency) if row.avg_latency else None
            existing.unique_domains = row.unique_domains or 0
        else:
            rollup = QueryRollup(
                bucket_start=day_start,
                granularity="daily",
                client_id=row.client_id,
                node_id=row.node_id,
                total_queries=row.total or 0,
                blocked_queries=row.blocked or 0,
                nxdomain_count=row.nxdomain or 0,
                servfail_count=row.servfail or 0,
                cache_hits=row.cache_hits or 0,
                avg_latency_ms=int(row.avg_latency) if row.avg_latency else None,
                unique_domains=row.unique_domains or 0,
            )
            db.add(rollup)
        count += 1

    db.commit()
    return count


def run_rollup_job(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    previous_hour = current_hour - timedelta(hours=1)

    current_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    previous_day = current_day - timedelta(days=1)

    hourly_count = compute_hourly_rollup(db, previous_hour)
    daily_count = 0

    if now.hour < 2:
        daily_count = compute_daily_rollup(db, previous_day)

    log.info(f"Rollup job: {hourly_count} hourly, {daily_count} daily")
    return {"hourly": hourly_count, "daily": daily_count}


def get_dashboard_stats(db: Session, hours: int = 24) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    totals = (
        db.query(
            func.sum(QueryRollup.total_queries).label("total"),
            func.sum(QueryRollup.blocked_queries).label("blocked"),
            func.sum(QueryRollup.nxdomain_count).label("nxdomain"),
            func.sum(QueryRollup.servfail_count).label("servfail"),
            func.sum(QueryRollup.cache_hits).label("cache_hits"),
            func.avg(QueryRollup.avg_latency_ms).label("avg_latency"),
        )
        .filter(QueryRollup.bucket_start >= cutoff, QueryRollup.granularity == "hourly")
        .one()
    )

    return {
        "total_queries": totals.total or 0,
        "blocked_queries": totals.blocked or 0,
        "nxdomain_count": totals.nxdomain or 0,
        "servfail_count": totals.servfail or 0,
        "cache_hits": totals.cache_hits or 0,
        "avg_latency_ms": int(totals.avg_latency) if totals.avg_latency else 0,
        "blocked_pct": round((totals.blocked or 0) / max(totals.total or 1, 1) * 100, 1),
        "cache_hit_pct": round((totals.cache_hits or 0) / max(totals.total or 1, 1) * 100, 1),
    }
