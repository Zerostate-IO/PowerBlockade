from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DNSQueryEvent(Base):
    __tablename__ = "dns_query_events"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True)
    event_id: Mapped[str | None] = mapped_column(sa.String(64), unique=True)

    ts: Mapped[object] = mapped_column(sa.DateTime(timezone=True), index=True)
    node_id: Mapped[int | None] = mapped_column(
        sa.Integer(), sa.ForeignKey("nodes.id", ondelete="SET NULL")
    )

    client_ip: Mapped[str] = mapped_column(sa.String(64), index=True)
    client_id: Mapped[int | None] = mapped_column(
        sa.BigInteger(), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )

    qname: Mapped[str] = mapped_column(sa.Text())
    qtype: Mapped[int] = mapped_column(sa.Integer())
    rcode: Mapped[int] = mapped_column(sa.Integer())
    blocked: Mapped[bool] = mapped_column(sa.Boolean())

    block_reason: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    blocklist_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
