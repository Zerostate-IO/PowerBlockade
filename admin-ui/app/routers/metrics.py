from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.dns_query_event import DNSQueryEvent


router = APIRouter()


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    """Prometheus metrics endpoint for PowerBlockade."""
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

    hit_rate = (cache_hits / total * 100) if total > 0 else 0
    block_rate = (blocked / total * 100) if total > 0 else 0
    qps = total / 86400 if total > 0 else 0

    lines = [
        f"# Prometheus metrics for PowerBlockade",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}",
        f"",
        f"powerblockade_queries_total {total}",
        f"powerblockade_blocked_total {blocked}",
        f"powerblockade_block_rate {block_rate}",
        f"powerblockade_cache_hits_total {cache_hits}",
        f"powerblockade_cache_hit_rate {hit_rate}",
        f"powerblockade_time_saved_seconds {int(time_saved_total / 1000)}",
        f"powerblockade_qps {qps:.2f}",
    ]

    return Response("\n".join(lines), media_type="text/plain; version=0.0.4")
