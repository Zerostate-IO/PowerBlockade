"""Add blocklist_entries table for domain search

Revision ID: 0013_blocklist_entries
Revises: 0012_blocklist_schedules
Create Date: 2026-01-28

"""

import sqlalchemy as sa

from alembic import op

revision = "0013_blocklist_entries"
down_revision = "0012_blocklist_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blocklist_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("domain", sa.String(255), nullable=False, index=True),
        sa.Column(
            "blocklist_id",
            sa.BigInteger(),
            sa.ForeignKey("blocklists.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_blocklist_entry_domain_list",
        "blocklist_entries",
        ["domain", "blocklist_id"],
    )
    op.create_index(
        "ix_blocklist_entries_domain_lower",
        "blocklist_entries",
        [sa.text("LOWER(domain)")],
    )


def downgrade() -> None:
    op.drop_index("ix_blocklist_entries_domain_lower", table_name="blocklist_entries")
    op.drop_constraint("uq_blocklist_entry_domain_list", "blocklist_entries")
    op.drop_table("blocklist_entries")
