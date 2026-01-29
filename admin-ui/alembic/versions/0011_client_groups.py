"""Add client_groups table and group_id to clients

Revision ID: 0011_client_groups
Revises: 0010_node_metrics
Create Date: 2026-01-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_client_groups"
down_revision = "0010_node_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cidr", sa.String(50), nullable=True),
        sa.Column("color", sa.String(20), server_default="slate", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.add_column(
        "clients",
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("client_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_clients_group_id", "clients", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_clients_group_id", table_name="clients")
    op.drop_column("clients", "group_id")
    op.drop_table("client_groups")
