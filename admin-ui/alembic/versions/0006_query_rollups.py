"""Add query_rollups table

Revision ID: 0006
Revises: 0005
Create Date: 2026-01-28

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "query_rollups",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granularity", sa.String(10), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "total_queries",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "blocked_queries",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "nxdomain_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "servfail_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("cache_hits", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("avg_latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "unique_domains",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "bucket_start",
            "granularity",
            "client_id",
            "node_id",
            name="uq_rollup_bucket",
        ),
    )
    op.create_index("ix_rollup_bucket_start", "query_rollups", ["bucket_start"])
    op.create_index("ix_rollup_granularity", "query_rollups", ["granularity"])


def downgrade() -> None:
    op.drop_index("ix_rollup_granularity", table_name="query_rollups")
    op.drop_index("ix_rollup_bucket_start", table_name="query_rollups")
    op.drop_table("query_rollups")
