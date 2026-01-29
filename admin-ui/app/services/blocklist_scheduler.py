"""Blocklist schedule enforcement.

Enables/disables blocklists based on time-of-day schedules.
Checks current time against schedule_start, schedule_end, schedule_days fields.
Regenerates RPZ when blocklist enabled state changes.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.models.blocklist import Blocklist
from app.models.settings import get_setting

log = logging.getLogger(__name__)


def get_timezone(db) -> ZoneInfo:
    """Get configured timezone, default to UTC."""
    tz_str = get_setting(db, "timezone") or "UTC"
    try:
        return ZoneInfo(tz_str)
    except Exception:
        log.warning(f"Invalid timezone '{tz_str}', falling back to UTC")
        return ZoneInfo("UTC")


def parse_time(time_str: str) -> tuple[int, int] | None:
    """Parse HH:MM string to (hour, minute) tuple."""
    if not time_str or ":" not in time_str:
        return None
    try:
        parts = time_str.split(":")
        return (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


def is_time_in_range(
    current_hour: int,
    current_minute: int,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
) -> bool:
    """Check if current time is within start-end range (handles overnight spans)."""
    current = current_hour * 60 + current_minute
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute

    if start <= end:
        # Normal range (e.g., 09:00 - 17:00)
        return start <= current < end
    else:
        # Overnight range (e.g., 22:00 - 06:00)
        return current >= start or current < end


def is_blocklist_active(bl: Blocklist, now: datetime) -> bool:
    """Determine if blocklist should be active based on its schedule.

    Returns True if:
    - schedule_enabled is False (no schedule = always active)
    - Current time/day matches the schedule
    """
    if not bl.schedule_enabled:
        return True

    # Parse schedule fields
    start = parse_time(bl.schedule_start or "")
    end = parse_time(bl.schedule_end or "")

    if not start or not end:
        # Invalid schedule config = always active
        return True

    # Check day of week
    schedule_days = (bl.schedule_days or "").lower()
    if schedule_days:
        day_map = {
            0: "mon",
            1: "tue",
            2: "wed",
            3: "thu",
            4: "fri",
            5: "sat",
            6: "sun",
        }
        current_day = day_map.get(now.weekday(), "")
        if current_day and current_day not in schedule_days:
            return False

    # Check time range
    return is_time_in_range(now.hour, now.minute, start[0], start[1], end[0], end[1])


def run_schedule_check() -> dict[str, int | str]:
    """Check all blocklist schedules and update enabled states.

    Returns dict with counts of blocklists enabled/disabled by schedule.
    """
    from app.services.scheduler import regenerate_rpz

    db = SessionLocal()
    try:
        tz = get_timezone(db)
        now = datetime.now(tz)

        blocklists = db.query(Blocklist).filter(Blocklist.schedule_enabled.is_(True)).all()

        enabled_count = 0
        disabled_count = 0
        changed = False

        for bl in blocklists:
            should_be_active = is_blocklist_active(bl, now)

            if should_be_active and not bl.enabled:
                bl.enabled = True
                enabled_count += 1
                changed = True
                log.info(f"Schedule enabled blocklist '{bl.name}'")
            elif not should_be_active and bl.enabled:
                bl.enabled = False
                disabled_count += 1
                changed = True
                log.info(f"Schedule disabled blocklist '{bl.name}'")

        if changed:
            db.commit()
            regenerate_rpz(db)
            log.info(f"Schedule check: enabled={enabled_count}, disabled={disabled_count}")

        return {"enabled": enabled_count, "disabled": disabled_count}

    except Exception as e:
        log.error(f"Schedule check failed: {e}")
        db.rollback()
        return {"enabled": 0, "disabled": 0, "error": str(e)}
    finally:
        db.close()
