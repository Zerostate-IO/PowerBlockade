"""Add node lifecycle states and quarantine tracking

Revision ID: 0016
Revises: 0015_node_commands
Create Date: 2026-02-25

Adds:
- NodeStatus enum values (stale, offline, quarantine)
- last_heartbeat column for heartbeat tracking
- quarantine_entry_time, quarantine_reason, approved_by, approved_at columns

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015_node_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns for quarantine tracking
    op.add_column("nodes", sa.Column("last_heartbeat", sa.DateTime(), nullable=True))
    op.add_column("nodes", sa.Column("quarantine_entry_time", sa.DateTime(), nullable=True))
    op.add_column("nodes", sa.Column("quarantine_reason", sa.Text(), nullable=True))
    op.add_column("nodes", sa.Column("approved_by", sa.Integer(), nullable=True))
    op.add_column("nodes", sa.Column("approved_at", sa.DateTime(), nullable=True))

    # Populate last_heartbeat from last_seen for existing nodes
    op.execute(
        "UPDATE nodes SET last_heartbeat = last_seen WHERE last_heartbeat IS NULL AND last_seen IS NOT NULL"
    )

    # Note: status column already exists as VARCHAR(20) with default 'pending'
    # New values (stale, offline, quarantine) are valid strings in the existing column


def downgrade() -> None:
    op.drop_column("nodes", "approved_at")
    op.drop_column("nodes", "approved_by")
    op.drop_column("nodes", "quarantine_reason")
    op.drop_column("nodes", "quarantine_entry_time")
    op.drop_column("nodes", "last_heartbeat")
