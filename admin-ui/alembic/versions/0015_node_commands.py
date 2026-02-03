"""Add node_commands table

Revision ID: 0015
Revises: 0014
Create Date: 2026-02-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_node_commands"
down_revision = "0014_drop_node_event_seq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_commands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "node_id",
            sa.Integer(),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("command", sa.String(64), nullable=False),
        sa.Column("params", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
    )
    op.create_index("ix_node_commands_pending", "node_commands", ["node_id", "executed_at"])


def downgrade() -> None:
    op.drop_index("ix_node_commands_pending")
    op.drop_table("node_commands")
