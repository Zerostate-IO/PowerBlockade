from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(sa.Integer(), primary_key=True)
    key: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), onupdate=sa.text("NOW()"), nullable=True
    )


DEFAULTS = {
    "retention_events_days": "30",
    "retention_rollups_days": "365",
    "rollup_enabled": "true",
    "ptr_resolution_enabled": "true",
}


def get_setting(db, key: str) -> str:
    row = db.query(Settings).filter(Settings.key == key).one_or_none()
    if row:
        return row.value
    return DEFAULTS.get(key, "")


def set_setting(db, key: str, value: str) -> None:
    row = db.query(Settings).filter(Settings.key == key).one_or_none()
    if row:
        row.value = value
    else:
        row = Settings(key=key, value=value)
        db.add(row)
    db.commit()


def get_retention_events_days(db) -> int:
    return int(get_setting(db, "retention_events_days") or "30")


def get_retention_rollups_days(db) -> int:
    return int(get_setting(db, "retention_rollups_days") or "365")
