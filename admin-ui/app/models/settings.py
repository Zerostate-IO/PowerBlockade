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
    "retention_events_days": "15",
    "retention_rollups_days": "365",
    "retention_node_metrics_days": "365",
    "rollup_enabled": "true",
    "ptr_resolution_enabled": "true",
    "precache_enabled": "true",
    "precache_domain_count": "1000",
    "precache_refresh_minutes": "30",
    "precache_ignore_ttl": "false",
    "precache_custom_refresh_minutes": "60",
    "precache_dns_server": "recursor",
    "timezone": "UTC",
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
    return int(get_setting(db, "retention_events_days") or "15")


def get_retention_rollups_days(db) -> int:
    return int(get_setting(db, "retention_rollups_days") or "365")


def get_retention_node_metrics_days(db) -> int:
    return int(get_setting(db, "retention_node_metrics_days") or "90")


def get_precache_enabled(db) -> bool:
    return get_setting(db, "precache_enabled").lower() == "true"


def get_precache_domain_count(db) -> int:
    return int(get_setting(db, "precache_domain_count") or "1000")


def get_precache_refresh_minutes(db) -> int:
    return int(get_setting(db, "precache_refresh_minutes") or "30")


def get_precache_ignore_ttl(db) -> bool:
    return get_setting(db, "precache_ignore_ttl").lower() == "true"


def get_precache_custom_refresh_minutes(db) -> int:
    return int(get_setting(db, "precache_custom_refresh_minutes") or "60")


def get_precache_dns_server(db) -> str:
    return get_setting(db, "precache_dns_server") or "recursor"


def get_timezone(db) -> str:
    return get_setting(db, "timezone") or "UTC"
