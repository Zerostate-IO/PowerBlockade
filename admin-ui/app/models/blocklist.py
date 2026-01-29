from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Blocklist(Base):
    __tablename__ = "blocklists"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    url: Mapped[str] = mapped_column(sa.Text(), unique=True)
    format: Mapped[str] = mapped_column(sa.String(50))
    list_type: Mapped[str] = mapped_column(sa.String(10), server_default=sa.text("'block'"))
    enabled: Mapped[bool] = mapped_column(sa.Boolean(), server_default=sa.text("true"))

    update_frequency_hours: Mapped[int] = mapped_column(sa.Integer(), server_default=sa.text("24"))
    last_updated: Mapped[object | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_update_status: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    entry_count: Mapped[int] = mapped_column(sa.Integer(), server_default=sa.text("0"))

    etag: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    schedule_enabled: Mapped[bool] = mapped_column(sa.Boolean(), server_default=sa.text("false"))
    schedule_start: Mapped[str | None] = mapped_column(sa.String(5), nullable=True)
    schedule_end: Mapped[str | None] = mapped_column(sa.String(5), nullable=True)
    schedule_days: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)

    created_at: Mapped[object] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()")
    )
