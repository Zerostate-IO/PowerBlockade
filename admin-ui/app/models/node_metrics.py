from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NodeMetrics(Base):
    """Stores performance metrics pushed from nodes (sync-agent).

    Each row represents a snapshot of recursor metrics from a node.
    Prometheus scrapes admin-ui /metrics which aggregates the latest
    metrics from all nodes.
    """

    __tablename__ = "node_metrics"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True)
    node_id: Mapped[int] = mapped_column(
        sa.BigInteger(),
        sa.ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ts: Mapped[object] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("NOW()"),
        nullable=False,
        index=True,
    )

    cache_hits: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)
    cache_misses: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)
    cache_entries: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)

    packetcache_hits: Mapped[int] = mapped_column(
        sa.BigInteger(), server_default="0", nullable=False
    )
    packetcache_misses: Mapped[int] = mapped_column(
        sa.BigInteger(), server_default="0", nullable=False
    )

    answers_0_1: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)
    answers_1_10: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)
    answers_10_100: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)
    answers_100_1000: Mapped[int] = mapped_column(
        sa.BigInteger(), server_default="0", nullable=False
    )
    answers_slow: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)

    concurrent_queries: Mapped[int] = mapped_column(
        sa.BigInteger(), server_default="0", nullable=False
    )
    outgoing_timeouts: Mapped[int] = mapped_column(
        sa.BigInteger(), server_default="0", nullable=False
    )
    servfail_answers: Mapped[int] = mapped_column(
        sa.BigInteger(), server_default="0", nullable=False
    )
    nxdomain_answers: Mapped[int] = mapped_column(
        sa.BigInteger(), server_default="0", nullable=False
    )

    questions: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)
    all_outqueries: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)

    uptime_seconds: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)
