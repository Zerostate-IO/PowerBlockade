from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ManualEntry(Base):
    __tablename__ = "manual_entries"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True)
    domain: Mapped[str] = mapped_column(sa.String(255), unique=True)
    entry_type: Mapped[str] = mapped_column(sa.String(10))  # allow|block
    comment: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[object] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()")
    )
