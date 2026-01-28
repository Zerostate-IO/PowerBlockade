"""Add client_resolver_rules table

Revision ID: 0005
Revises: 0004
Create Date: 2026-01-28

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_resolver_rules",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("subnet", sa.String(64), nullable=False),
        sa.Column("nameserver", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subnet"),
    )
    op.create_index("ix_client_resolver_rules_priority", "client_resolver_rules", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_client_resolver_rules_priority", table_name="client_resolver_rules")
    op.drop_table("client_resolver_rules")
