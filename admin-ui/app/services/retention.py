from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.models.dns_query_event import DNSQueryEvent
from app.models.node_metrics import NodeMetrics
from app.models.query_rollup import QueryRollup
from app.models.settings import (
    get_retention_events_days,
    get_retention_node_metrics_days,
    get_retention_rollups_days,
)

log = logging.getLogger(__name__)


def cleanup_old_events(db: Session, days: int | None = None) -> int:
    if days is None:
        days = get_retention_events_days(db)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    result = cast(CursorResult, db.execute(delete(DNSQueryEvent).where(DNSQueryEvent.ts < cutoff)))
    db.commit()

    deleted = result.rowcount or 0
    log.info(f"Retention: deleted {deleted} events older than {days} days")
    return deleted


def cleanup_old_rollups(db: Session, days: int | None = None) -> int:
    if days is None:
        days = get_retention_rollups_days(db)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    result = cast(
        CursorResult, db.execute(delete(QueryRollup).where(QueryRollup.bucket_start < cutoff))
    )
    db.commit()

    deleted = result.rowcount or 0
    log.info(f"Retention: deleted {deleted} rollups older than {days} days")
    return deleted


def cleanup_old_node_metrics(db: Session, days: int | None = None) -> int:
    if days is None:
        days = get_retention_node_metrics_days(db)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    result = cast(CursorResult, db.execute(delete(NodeMetrics).where(NodeMetrics.ts < cutoff)))
    db.commit()

    deleted = result.rowcount or 0
    log.info(f"Retention: deleted {deleted} node_metrics older than {days} days")
    return deleted


def run_retention_job(db: Session) -> dict:
    events_deleted = cleanup_old_events(db)
    rollups_deleted = cleanup_old_rollups(db)
    node_metrics_deleted = cleanup_old_node_metrics(db)

    return {
        "events_deleted": events_deleted,
        "rollups_deleted": rollups_deleted,
        "node_metrics_deleted": node_metrics_deleted,
    }
