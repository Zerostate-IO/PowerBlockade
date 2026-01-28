from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.forward_zone import ForwardZone


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    api_key: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)

    ip_address: Mapped[str | None] = mapped_column(sa.String(45), nullable=True)
    version: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20), server_default="pending", nullable=False)
    last_seen: Mapped[object | None] = mapped_column(sa.DateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    config_version: Mapped[int] = mapped_column(sa.Integer(), server_default="0", nullable=False)
    queries_total: Mapped[int] = mapped_column(sa.BigInteger(), server_default="0", nullable=False)
    queries_blocked: Mapped[int] = mapped_column(
        sa.BigInteger(), server_default="0", nullable=False
    )
    created_at: Mapped[object] = mapped_column(sa.DateTime(), server_default=sa.text("NOW()"))

    forward_zones: Mapped[list["ForwardZone"]] = relationship(
        "ForwardZone", back_populates="node", cascade="all, delete-orphan"
    )
