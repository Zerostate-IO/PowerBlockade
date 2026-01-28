from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True)
    ip: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)

    display_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    rdns_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    rdns_last_resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    rdns_last_error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()")
    )
    last_seen: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
