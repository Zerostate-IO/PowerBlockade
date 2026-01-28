"""Add config_changes table for audit trail

Revision ID: 0008_config_changes
Revises: 0007_settings
Create Date: 2026-01-28
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0008_config_changes"
down_revision = "0007_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "config_changes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False, index=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("before_data", JSONB, nullable=True),
        sa.Column("after_data", JSONB, nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("config_changes")
