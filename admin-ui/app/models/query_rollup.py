from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QueryRollup(Base):
    """
    Pre-aggregated query statistics for fast dashboard rendering.
    Granularity: hourly or daily buckets per client/node.
    """

    __tablename__ = "query_rollups"
    __table_args__ = (
        sa.UniqueConstraint(
            "bucket_start",
            "granularity",
            "client_id",
            "node_id",
            name="uq_rollup_bucket",
        ),
        sa.Index("ix_rollup_bucket_start", "bucket_start"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)

    bucket_start: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    granularity: Mapped[str] = mapped_column(sa.String(10), nullable=False)

    client_id: Mapped[int | None] = mapped_column(
        sa.BigInteger(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True
    )
    node_id: Mapped[int | None] = mapped_column(
        sa.BigInteger(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True
    )

    total_queries: Mapped[int] = mapped_column(sa.BigInteger(), default=0, nullable=False)
    blocked_queries: Mapped[int] = mapped_column(sa.BigInteger(), default=0, nullable=False)
    nxdomain_count: Mapped[int] = mapped_column(sa.BigInteger(), default=0, nullable=False)
    servfail_count: Mapped[int] = mapped_column(sa.BigInteger(), default=0, nullable=False)
    cache_hits: Mapped[int] = mapped_column(sa.BigInteger(), default=0, nullable=False)
    avg_latency_ms: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)

    unique_domains: Mapped[int] = mapped_column(sa.BigInteger(), default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), onupdate=sa.text("NOW()"), nullable=True
    )
