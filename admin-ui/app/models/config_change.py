from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Use JSONB on PostgreSQL, plain JSON on SQLite (for tests)
JSONVariant = sa.JSON().with_variant(JSONB, "postgresql")


class ConfigChange(Base):
    __tablename__ = "config_changes"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True)

    entity_type: Mapped[str] = mapped_column(sa.String(50), index=True)
    entity_id: Mapped[int | None] = mapped_column(sa.BigInteger(), nullable=True, index=True)

    action: Mapped[str] = mapped_column(sa.String(20))
    actor_user_id: Mapped[int | None] = mapped_column(
        sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    comment: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), index=True
    )
