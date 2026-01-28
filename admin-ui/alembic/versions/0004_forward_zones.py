"""Add forward_zones table

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-28

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forward_zones",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("servers", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain"),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["nodes.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_forward_zones_node_id", "forward_zones", ["node_id"])


def downgrade() -> None:
    op.drop_index("ix_forward_zones_node_id", table_name="forward_zones")
    op.drop_table("forward_zones")
