from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NodeCommand(Base):
    """Pending commands for nodes to execute."""

    __tablename__ = "node_commands"

    id: Mapped[int] = mapped_column(sa.Integer(), primary_key=True)
    node_id: Mapped[int | None] = mapped_column(
        sa.Integer(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True
    )
    command: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    params: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()")
    )
    executed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
