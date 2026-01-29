"""Add blocklist schedule fields

Revision ID: 0012
Revises: 0011
Create Date: 2026-01-28

"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blocklists",
        sa.Column(
            "schedule_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(
        "blocklists",
        sa.Column("schedule_start", sa.String(5), nullable=True),
    )
    op.add_column(
        "blocklists",
        sa.Column("schedule_end", sa.String(5), nullable=True),
    )
    op.add_column(
        "blocklists",
        sa.Column("schedule_days", sa.String(30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blocklists", "schedule_days")
    op.drop_column("blocklists", "schedule_end")
    op.drop_column("blocklists", "schedule_start")
    op.drop_column("blocklists", "schedule_enabled")
