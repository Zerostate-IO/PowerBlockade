"""blocklists list_type

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-28

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blocklists",
        sa.Column(
            "list_type",
            sa.String(length=10),
            server_default=sa.text("'block'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("blocklists", "list_type")
