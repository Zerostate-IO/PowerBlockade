from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ClientResolverRule(Base):
    """
    Maps IP subnets to upstream DNS servers for PTR (reverse DNS) lookups.
    Used to resolve client hostnames like Pi-hole does.

    Example: 192.168.1.0/24 -> 192.168.1.1 (local router for LAN clients)
    """

    __tablename__ = "client_resolver_rules"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True)
    subnet: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    nameserver: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean(), default=True, nullable=False)
    priority: Mapped[int] = mapped_column(sa.Integer(), default=100, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    created_at: Mapped[object] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()")
    )
    updated_at: Mapped[object | None] = mapped_column(
        sa.DateTime(timezone=True), onupdate=sa.text("NOW()"), nullable=True
    )
