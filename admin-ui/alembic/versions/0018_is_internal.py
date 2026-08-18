"""Add is_internal flag to dns_query_events

Flags events whose client is in an internal (docker/vpn) subnet so
user-facing analytics can exclude container-internal traffic such as
precache warming (issue #48).

Revision ID: 0018
Revises: 0017_node_metrics_longterm_index
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_is_internal"
down_revision = "0017_node_metrics_longterm_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dns_query_events",
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Keep the default filter (is_internal = false) fast as it grows.
    op.create_index("ix_dns_query_events_is_internal", "dns_query_events", ["is_internal"])


def downgrade() -> None:
    op.drop_index("ix_dns_query_events_is_internal", table_name="dns_query_events")
    op.drop_column("dns_query_events", "is_internal")
