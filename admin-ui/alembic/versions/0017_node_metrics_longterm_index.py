"""Add composite index for long-term node metrics queries

Revision ID: 0017
Revises: 0016
Create Date: 2026-02-25
"""

from __future__ import annotations

from alembic import op

revision = "0017_node_metrics_longterm_index"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_node_metrics_node_id_ts",
        "node_metrics",
        ["node_id", "ts"],
    )


def downgrade() -> None:
    op.drop_index("ix_node_metrics_node_id_ts", table_name="node_metrics")
