from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.node import Node
from app.models.node_metrics import NodeMetrics
from app.services.rollups import get_dashboard_stats

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
    stats = get_dashboard_stats(db, hours=24)

    total = max(int(stats.get("total_queries", 0)), 0)
    blocked = int(stats.get("blocked_queries", 0))
    cache_hits = int(stats.get("cache_hits", 0))
    time_saved_ms = float(stats.get("time_saved_ms", 0))
    qps = float(stats.get("qps", 0))
    blocked_pct = float(stats.get("blocked_pct", 0))
    cache_hit_pct = float(stats.get("cache_hit_pct", 0))
    time_saved_seconds = int(time_saved_ms / 1000)

    # Metadata from bounded stats cache
    cache_age = float(stats.get("cache_age_seconds", 0))
    rollup_lag = float(stats.get("rollup_lag_seconds", 0))
    edge_delta = int(stats.get("edge_delta_total", 0))

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
        f"powerblockade_block_rate {blocked_pct:.2f}",
        "",
        "# HELP powerblockade_cache_hits_total Estimated cache hits in 24h",
        "# TYPE powerblockade_cache_hits_total gauge",
        f"powerblockade_cache_hits_total {cache_hits}",
        "",
        "# HELP powerblockade_cache_hit_rate Cache hit percentage",
        "# TYPE powerblockade_cache_hit_rate gauge",
        f"powerblockade_cache_hit_rate {cache_hit_pct:.2f}",
        "",
        "# HELP powerblockade_time_saved_seconds Time saved by cache",
        "# TYPE powerblockade_time_saved_seconds gauge",
        f"powerblockade_time_saved_seconds {time_saved_seconds}",
        "",
        "# HELP powerblockade_qps Queries per second (24h avg)",
        "# TYPE powerblockade_qps gauge",
        f"powerblockade_qps {qps:.2f}",
        "",
        "# HELP powerblockade_stats_cache_age_seconds Age of the cached stats in seconds",
        "# TYPE powerblockade_stats_cache_age_seconds gauge",
        f"powerblockade_stats_cache_age_seconds {cache_age:.1f}",
        "",
        "# HELP powerblockade_rollup_lag_seconds Seconds since last included rollup bucket",
        "# TYPE powerblockade_rollup_lag_seconds gauge",
        f"powerblockade_rollup_lag_seconds {rollup_lag:.1f}",
        "",
        "# HELP powerblockade_stats_edge_delta_total Raw edge events included in this sample",
        "# TYPE powerblockade_stats_edge_delta_total gauge",
        f"powerblockade_stats_edge_delta_total {edge_delta}",
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
