from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.dns_query_event import DNSQueryEvent
from app.models.node import Node
from app.models.node_metrics import NodeMetrics

router = APIRouter()


def _get_latest_node_metrics(db: Session) -> list[tuple[str, NodeMetrics]]:
    subq = (
        db.query(NodeMetrics.node_id, sa.func.max(NodeMetrics.id).label("max_id"))
        .group_by(NodeMetrics.node_id)
        .subquery()
    )

    results = (
        db.query(Node.name, NodeMetrics)
        .join(subq, NodeMetrics.id == subq.c.max_id)
        .join(Node, Node.id == NodeMetrics.node_id)
        .all()
    )

    return [(name, m) for name, m in results]


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)):
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
        "# HELP powerblockade_queries_total Total DNS queries in 24h",
        "# TYPE powerblockade_queries_total gauge",
        f"powerblockade_queries_total {total}",
        "",
        "# HELP powerblockade_blocked_total Blocked queries in 24h",
        "# TYPE powerblockade_blocked_total gauge",
        f"powerblockade_blocked_total {blocked}",
        "",
        "# HELP powerblockade_block_rate Block percentage",
        "# TYPE powerblockade_block_rate gauge",
        f"powerblockade_block_rate {block_rate:.2f}",
        "",
        "# HELP powerblockade_cache_hits_total Estimated cache hits in 24h",
        "# TYPE powerblockade_cache_hits_total gauge",
        f"powerblockade_cache_hits_total {cache_hits}",
        "",
        "# HELP powerblockade_cache_hit_rate Cache hit percentage",
        "# TYPE powerblockade_cache_hit_rate gauge",
        f"powerblockade_cache_hit_rate {hit_rate:.2f}",
        "",
        "# HELP powerblockade_time_saved_seconds Time saved by cache",
        "# TYPE powerblockade_time_saved_seconds gauge",
        f"powerblockade_time_saved_seconds {int(time_saved_total / 1000)}",
        "",
        "# HELP powerblockade_qps Queries per second (24h avg)",
        "# TYPE powerblockade_qps gauge",
        f"powerblockade_qps {qps:.2f}",
    ]

    node_metrics = _get_latest_node_metrics(db)
    if node_metrics:
        lines.extend(
            [
                "",
                "# HELP powerblockade_recursor_cache_hits Recursor cache hits by node",
                "# TYPE powerblockade_recursor_cache_hits counter",
            ]
        )
        for name, m in node_metrics:
            lines.append(f'powerblockade_recursor_cache_hits{{node="{name}"}} {m.cache_hits}')

        lines.extend(
            [
                "",
                "# HELP powerblockade_recursor_cache_misses Recursor cache misses by node",
                "# TYPE powerblockade_recursor_cache_misses counter",
            ]
        )
        for name, m in node_metrics:
            lines.append(f'powerblockade_recursor_cache_misses{{node="{name}"}} {m.cache_misses}')

        lines.extend(
            [
                "",
                "# HELP powerblockade_recursor_cache_entries Current cache entries by node",
                "# TYPE powerblockade_recursor_cache_entries gauge",
            ]
        )
        for name, m in node_metrics:
            lines.append(f'powerblockade_recursor_cache_entries{{node="{name}"}} {m.cache_entries}')

        lines.extend(
            [
                "",
                "# HELP powerblockade_recursor_answers_latency Answer latency buckets by node",
                "# TYPE powerblockade_recursor_answers_latency counter",
            ]
        )
        for name, m in node_metrics:
            lines.append(
                f'powerblockade_recursor_answers_latency{{node="{name}",le="1"}} {m.answers_0_1}'
            )
            lines.append(
                f'powerblockade_recursor_answers_latency{{node="{name}",le="10"}} {m.answers_1_10}'
            )
            lines.append(
                f'powerblockade_recursor_answers_latency{{node="{name}",le="100"}} {m.answers_10_100}'
            )
            lines.append(
                f'powerblockade_recursor_answers_latency{{node="{name}",le="1000"}} {m.answers_100_1000}'
            )
            lines.append(
                f'powerblockade_recursor_answers_latency{{node="{name}",le="+Inf"}} {m.answers_slow}'
            )

        lines.extend(
            [
                "",
                "# HELP powerblockade_recursor_concurrent_queries Current concurrent queries by node",
                "# TYPE powerblockade_recursor_concurrent_queries gauge",
            ]
        )
        for name, m in node_metrics:
            lines.append(
                f'powerblockade_recursor_concurrent_queries{{node="{name}"}} {m.concurrent_queries}'
            )

        lines.extend(
            [
                "",
                "# HELP powerblockade_recursor_outgoing_timeouts Outgoing query timeouts by node",
                "# TYPE powerblockade_recursor_outgoing_timeouts counter",
            ]
        )
        for name, m in node_metrics:
            lines.append(
                f'powerblockade_recursor_outgoing_timeouts{{node="{name}"}} {m.outgoing_timeouts}'
            )

        lines.extend(
            [
                "",
                "# HELP powerblockade_recursor_servfail_answers SERVFAIL responses by node",
                "# TYPE powerblockade_recursor_servfail_answers counter",
            ]
        )
        for name, m in node_metrics:
            lines.append(
                f'powerblockade_recursor_servfail_answers{{node="{name}"}} {m.servfail_answers}'
            )

        lines.extend(
            [
                "",
                "# HELP powerblockade_recursor_questions Total questions received by node",
                "# TYPE powerblockade_recursor_questions counter",
            ]
        )
        for name, m in node_metrics:
            lines.append(f'powerblockade_recursor_questions{{node="{name}"}} {m.questions}')

        lines.extend(
            [
                "",
                "# HELP powerblockade_recursor_uptime_seconds Recursor uptime by node",
                "# TYPE powerblockade_recursor_uptime_seconds counter",
            ]
        )
        for name, m in node_metrics:
            lines.append(
                f'powerblockade_recursor_uptime_seconds{{node="{name}"}} {m.uptime_seconds}'
            )

    lines.append("")
    return Response("\n".join(lines), media_type="text/plain; version=0.0.4")
