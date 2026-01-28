"""Add node_metrics table for push-based metrics

Revision ID: 0010_node_metrics
Revises: 0009_event_seq
Create Date: 2026-01-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_node_metrics"
down_revision = "0009_event_seq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("cache_hits", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("cache_misses", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("cache_entries", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("packetcache_hits", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("packetcache_misses", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("answers_0_1", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("answers_1_10", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("answers_10_100", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("answers_100_1000", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("answers_slow", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("concurrent_queries", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("outgoing_timeouts", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("servfail_answers", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("nxdomain_answers", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("questions", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("all_outqueries", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("uptime_seconds", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_index("ix_node_metrics_node_id", "node_metrics", ["node_id"])
    op.create_index("ix_node_metrics_ts", "node_metrics", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_node_metrics_ts", table_name="node_metrics")
    op.drop_index("ix_node_metrics_node_id", table_name="node_metrics")
    op.drop_table("node_metrics")
