"""drop uq_node_event_seq constraint

Revision ID: 0014
Revises: 0013
Create Date: 2026-02-02
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_node_event_seq", "dns_query_events", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("uq_node_event_seq", "dns_query_events", ["node_id", "event_seq"])
