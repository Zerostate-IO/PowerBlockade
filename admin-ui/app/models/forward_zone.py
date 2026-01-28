from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.node import Node


class ForwardZone(Base):
    __tablename__ = "forward_zones"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True)
    domain: Mapped[str] = mapped_column(sa.String(255), unique=True)
    servers: Mapped[str] = mapped_column(sa.Text())
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean(), server_default=sa.text("true"))

    node_id: Mapped[int | None] = mapped_column(
        sa.BigInteger(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True, index=True
    )

    created_at: Mapped[object] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()")
    )
    updated_at: Mapped[object | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), onupdate=sa.text("NOW()")
    )

    node: Mapped[Node | None] = relationship("Node", back_populates="forward_zones")
