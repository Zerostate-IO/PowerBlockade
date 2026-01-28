"""Add event_seq for idempotent ingest

Revision ID: 0009_event_seq
Revises: 0008_config_changes
Create Date: 2026-01-28

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_event_seq"
down_revision = "0008_config_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dns_query_events", sa.Column("event_seq", sa.BigInteger(), nullable=True))
    op.create_unique_constraint("uq_node_event_seq", "dns_query_events", ["node_id", "event_seq"])


def downgrade() -> None:
    op.drop_constraint("uq_node_event_seq", "dns_query_events", type_="unique")
    op.drop_column("dns_query_events", "event_seq")
