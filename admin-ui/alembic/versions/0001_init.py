"""init

Revision ID: 0001
Revises:
Create Date: 2026-01-28

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=100), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("last_login", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("api_key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("version", sa.String(length=20), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("config_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("queries_total", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("queries_blocked", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("nodes")
    op.drop_table("users")
