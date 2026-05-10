from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.dns_query_event import DNSQueryEvent
from app.models.query_rollup import QueryRollup

log = logging.getLogger(__name__)

CACHE_HIT_LATENCY_THRESHOLD_MS = 5

# ---------------------------------------------------------------------------
# In-process TTL cache for get_dashboard_stats edge-query results
# ---------------------------------------------------------------------------
_stats_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_STATS_CACHE_TTL = 60.0  # seconds


def reset_stats_cache() -> None:
    """Clear the in-process stats cache.  Intended for test use."""
    _stats_cache.clear()


def compute_hourly_rollup(db: Session, hour_start: datetime) -> int:
    hour_end = hour_start + timedelta(hours=1)

    results = (
        db.query(
            DNSQueryEvent.client_id,
            DNSQueryEvent.node_id,
            func.count().label("total"),
            func.sum(func.cast(DNSQueryEvent.blocked, sa.Integer())).label("blocked"),
            func.sum(case((DNSQueryEvent.rcode == 3, 1), else_=0)).label("nxdomain"),
            func.sum(case((DNSQueryEvent.rcode == 2, 1), else_=0)).label("servfail"),
            func.sum(
                case(
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


def _raw_edge_aggregate(db: Session, start: datetime, end: datetime) -> dict[str, Any]:
    """Aggregate raw DNSQueryEvent over a bounded time range [start, end)."""
    row = (
        db.query(
            func.count().label("total"),
            func.sum(func.cast(DNSQueryEvent.blocked, sa.Integer())).label("blocked"),
            func.sum(case((DNSQueryEvent.rcode == 3, 1), else_=0)).label("nxdomain"),
            func.sum(case((DNSQueryEvent.rcode == 2, 1), else_=0)).label("servfail"),
            func.sum(
                case(
                    (DNSQueryEvent.latency_ms < CACHE_HIT_LATENCY_THRESHOLD_MS, 1),
                    else_=0,
                )
            ).label("cache_hits"),
            func.sum(DNSQueryEvent.latency_ms).label("latency_sum"),
            func.count(func.distinct(DNSQueryEvent.qname)).label("unique_domains"),
        )
        .filter(DNSQueryEvent.ts >= start, DNSQueryEvent.ts < end)
        .one()
    )
    total = row.total or 0
    blocked = int(row.blocked or 0)
    return {
        "total_queries": total,
        "blocked_queries": blocked,
        "nxdomain_count": int(row.nxdomain or 0),
        "servfail_count": int(row.servfail or 0),
        "cache_hits": int(row.cache_hits or 0),
        "latency_weighted_sum": int(row.latency_sum or 0),
        "unique_domains": int(row.unique_domains or 0),
    }


def _add_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {k: a.get(k, 0) + b.get(k, 0) for k in a}


def _build_result(
    accum: dict[str, Any],
    window_seconds: float,
    *,
    cache_age_seconds: float = 0.0,
    rollup_lag_seconds: float = 0.0,
    edge_delta_total: int = 0,
) -> dict[str, Any]:
    total = max(accum.get("total_queries", 0), 0)
    blocked = accum.get("blocked_queries", 0)
    cache_hits = accum.get("cache_hits", 0)
    latency_ws = accum.get("latency_weighted_sum", 0)
    unique_domains = accum.get("unique_domains", 0)
    avg_latency = int(latency_ws / total) if total > 0 else 0

    time_saved_ms = cache_hits * CACHE_HIT_LATENCY_THRESHOLD_MS
    qps = round(total / window_seconds, 2) if window_seconds > 0 else 0.0

    return {
        "total_queries": total,
        "blocked_queries": blocked,
        "nxdomain_count": accum.get("nxdomain_count", 0),
        "servfail_count": accum.get("servfail_count", 0),
        "cache_hits": cache_hits,
        "avg_latency_ms": avg_latency,
        "blocked_pct": round(blocked / max(total, 1) * 100, 1),
        "cache_hit_pct": round(cache_hits / max(total, 1) * 100, 1),
        "unique_domains": unique_domains,
        "time_saved_ms": time_saved_ms,
        "qps": qps,
        "block_rate": round(blocked / max(total, 1), 4),
        "cache_hit_rate": round(cache_hits / max(total, 1), 4),
        "cache_age_seconds": round(cache_age_seconds, 1),
        "rollup_lag_seconds": round(rollup_lag_seconds, 1),
        "edge_delta_total": edge_delta_total,
    }


def _cache_key(hours: int, start_bucket: datetime, current_bucket: datetime) -> str:
    return f"{hours}:{start_bucket.isoformat()}:{current_bucket.isoformat()}"


def get_dashboard_stats(db: Session, hours: int = 24) -> dict:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=hours)
    window_seconds = hours * 3600.0
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    start_hour = window_start.replace(minute=0, second=0, microsecond=0)

    if hours <= 1:
        raw = _raw_edge_aggregate(db, window_start, now)
        return _build_result(
            raw,
            window_seconds,
            cache_age_seconds=0.0,
            rollup_lag_seconds=0.0,
            edge_delta_total=raw.get("total_queries", 0),
        )

    full_start = start_hour + timedelta(hours=1) if window_start > start_hour else start_hour

    ck = _cache_key(hours, start_hour, current_hour)
    cached = _stats_cache.get(ck)
    if cached is not None:
        ts, data = cached
        age = time.monotonic() - ts
        if age < _STATS_CACHE_TTL:
            out = dict(data)
            out["cache_age_seconds"] = round(age, 1)
            return out

    latest_rollup_bucket = (
        db.query(func.max(QueryRollup.bucket_start))
        .filter(
            QueryRollup.bucket_start >= full_start,
            QueryRollup.bucket_start < current_hour,
            QueryRollup.granularity == "hourly",
        )
        .scalar()
    )
    rollup_lag = (now - latest_rollup_bucket).total_seconds() if latest_rollup_bucket else 0.0

    rollup_row = (
        db.query(
            func.sum(QueryRollup.total_queries).label("total"),
            func.sum(QueryRollup.blocked_queries).label("blocked"),
            func.sum(QueryRollup.nxdomain_count).label("nxdomain"),
            func.sum(QueryRollup.servfail_count).label("servfail"),
            func.sum(QueryRollup.cache_hits).label("cache_hits"),
            func.sum(
                QueryRollup.avg_latency_ms * QueryRollup.total_queries
            ).label("latency_weighted_sum"),
            func.sum(QueryRollup.unique_domains).label("unique_domains"),
        )
        .filter(
            QueryRollup.bucket_start >= full_start,
            QueryRollup.bucket_start < current_hour,
            QueryRollup.granularity == "hourly",
        )
        .one()
    )

    accum: dict[str, Any] = {
        "total_queries": int(rollup_row.total or 0),
        "blocked_queries": int(rollup_row.blocked or 0),
        "nxdomain_count": int(rollup_row.nxdomain or 0),
        "servfail_count": int(rollup_row.servfail or 0),
        "cache_hits": int(rollup_row.cache_hits or 0),
        "latency_weighted_sum": int(rollup_row.latency_weighted_sum or 0),
        "unique_domains": int(rollup_row.unique_domains or 0),
    }

    edge_delta_total = 0

    if window_start < full_start:
        start_edge = _raw_edge_aggregate(db, window_start, full_start)
        edge_delta_total += start_edge.get("total_queries", 0)
        accum = _add_dicts(accum, start_edge)

    if now > current_hour:
        current_edge = _raw_edge_aggregate(db, current_hour, now)
        edge_delta_total += current_edge.get("total_queries", 0)
        accum = _add_dicts(accum, current_edge)

    result = _build_result(
        accum,
        window_seconds,
        cache_age_seconds=0.0,
        rollup_lag_seconds=rollup_lag,
        edge_delta_total=edge_delta_total,
    )
    _stats_cache[ck] = (time.monotonic(), result)
    return result


def backfill_hourly_rollups(db: Session, hours: int = 24) -> int:
    hours = max(1, min(hours, 720))
    now = datetime.now(timezone.utc)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    total = 0
    for i in range(1, hours + 1):
        bucket = current_hour - timedelta(hours=i)
        total += compute_hourly_rollup(db, bucket)
    return total
