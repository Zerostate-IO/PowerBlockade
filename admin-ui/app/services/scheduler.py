from __future__ import annotations

import logging
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import cast

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

from app.db.session import SessionLocal
from app.models.blocklist import Blocklist
from app.models.manual_entry import ManualEntry
from app.models.node import Node
from app.models.node_metrics import NodeMetrics
from app.services.blocklist_scheduler import run_schedule_check
from app.services.precache import precache_warming_job
from app.services.retention import run_retention_job
from app.services.rollups import run_rollup_job
from app.services.rpz import parse_blocklist_text, render_rpz_whitelist, render_rpz_zone
from app.settings import get_settings

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def update_blocklists_job() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        blocklists = (
            db.query(Blocklist)
            .filter(
                Blocklist.enabled.is_(True),
                Blocklist.update_frequency_hours > 0,
            )
            .all()
        )

        updated_count = 0
        for bl in blocklists:
            if bl.last_updated is not None:
                last_upd = cast(datetime, bl.last_updated)
                next_update = last_upd + timedelta(hours=bl.update_frequency_hours)
                if now < next_update:
                    continue

            try:
                with urllib.request.urlopen(bl.url, timeout=30) as resp:
                    text = resp.read().decode("utf-8", errors="ignore")
                domains = parse_blocklist_text(text, bl.format)
                bl.last_update_status = "success"
                bl.last_error = None
                bl.entry_count = len(domains)
                bl.last_updated = now
                updated_count += 1
                log.info(f"Updated blocklist {bl.name}: {len(domains)} entries")
            except Exception as ex:
                bl.last_update_status = "failed"
                bl.last_error = str(ex)[:500]
                bl.last_updated = now
                log.warning(f"Failed to update blocklist {bl.name}: {ex}")

        if updated_count > 0:
            regenerate_rpz(db)

        db.commit()
        log.info(f"Blocklist update job: {updated_count} lists updated")
    except Exception as e:
        log.error(f"Blocklist update job failed: {e}")
        db.rollback()
    finally:
        db.close()


def regenerate_rpz(db) -> None:
    enabled = db.query(Blocklist).filter(Blocklist.enabled.is_(True)).all()
    allow_entries = db.query(ManualEntry).filter(ManualEntry.entry_type == "allow").all()
    block_entries = db.query(ManualEntry).filter(ManualEntry.entry_type == "block").all()

    blocked_domains: set[str] = {ent.domain for ent in block_entries}
    allow_domains: set[str] = {a.domain for a in allow_entries}

    for bl in enabled:
        if bl.last_update_status != "success":
            continue
        try:
            with urllib.request.urlopen(bl.url, timeout=30) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            domains = parse_blocklist_text(text, bl.format)
            if bl.list_type == "allow":
                allow_domains |= domains
            else:
                blocked_domains |= domains
        except Exception as e:
            log.warning(f"Failed to fetch blocklist '{bl.name}' during RPZ regeneration: {e}")

    out_dir = "/shared/rpz"
    os.makedirs(out_dir, exist_ok=True)

    effective_blocked = blocked_domains - allow_domains

    with open(os.path.join(out_dir, "blocklist-combined.rpz"), "w", encoding="utf-8") as f:
        f.write(render_rpz_zone(effective_blocked, policy_name="blocklist-combined"))
    with open(os.path.join(out_dir, "whitelist.rpz"), "w", encoding="utf-8") as f:
        f.write(render_rpz_whitelist(allow_domains))

    removed = len(blocked_domains) - len(effective_blocked)
    log.info(
        f"Regenerated RPZ: {len(effective_blocked)} blocked, {len(allow_domains)} allow, {removed} removed by whitelist"
    )


def rollup_job() -> None:
    db = SessionLocal()
    try:
        result = run_rollup_job(db)
        log.info(f"Rollup job completed: {result}")
    except Exception as e:
        log.error(f"Rollup job failed: {e}")
    finally:
        db.close()


def retention_job() -> None:
    db = SessionLocal()
    try:
        result = run_retention_job(db)
        log.info(f"Retention job completed: {result}")
    except Exception as e:
        log.error(f"Retention job failed: {e}")
    finally:
        db.close()


def blocklist_schedule_job() -> None:
    """Check blocklist schedules and enable/disable based on time."""
    try:
        result = run_schedule_check()
        if result.get("enabled", 0) or result.get("disabled", 0):
            log.info(f"Blocklist schedule job: {result}")
    except Exception as e:
        log.error(f"Blocklist schedule job failed: {e}")


def scrape_local_recursor_metrics() -> None:
    settings = get_settings()
    recursor_url = settings.recursor_api_url
    if not recursor_url:
        return

    db = SessionLocal()
    try:
        primary = db.query(Node).filter(Node.name == "primary", Node.status == "active").first()
        if not primary:
            return

        try:
            with urllib.request.urlopen(f"{recursor_url}/metrics", timeout=5) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            log.debug(f"Could not scrape local recursor: {e}")
            return

        metrics: dict[str, int] = {}
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            match = re.match(r"^pdns_recursor_(\w+)\s+([\d.]+)", line)
            if match:
                metrics[match.group(1)] = int(float(match.group(2)))

        if not metrics:
            return

        nm = NodeMetrics(
            node_id=primary.id,
            cache_hits=metrics.get("cache_hits", 0),
            cache_misses=metrics.get("cache_misses", 0),
            cache_entries=metrics.get("cache_entries", 0),
            packetcache_hits=metrics.get("packetcache_hits", 0),
            packetcache_misses=metrics.get("packetcache_misses", 0),
            answers_0_1=metrics.get("answers0_1", 0),
            answers_1_10=metrics.get("answers1_10", 0),
            answers_10_100=metrics.get("answers10_100", 0),
            answers_100_1000=metrics.get("answers100_1000", 0),
            answers_slow=metrics.get("answers_slow", 0),
            concurrent_queries=metrics.get("concurrent_queries", 0),
            outgoing_timeouts=metrics.get("outgoing_timeouts", 0),
            servfail_answers=metrics.get("servfail_answers", 0),
            nxdomain_answers=metrics.get("nxdomain_answers", 0),
            questions=metrics.get("questions", 0),
            all_outqueries=metrics.get("all_outqueries", 0),
            uptime_seconds=metrics.get("uptime_seconds", 0),
        )
        db.add(nm)
        db.commit()
        log.debug("Collected local recursor metrics for primary node")
    except Exception as e:
        log.error(f"Local metrics collection failed: {e}")
        db.rollback()
    finally:
        db.close()


def start_scheduler() -> None:
    global _scheduler

    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")

    _scheduler.add_job(
        update_blocklists_job,
        CronTrigger(minute="*/15"),
        id="blocklist_update",
        name="Update blocklists",
        replace_existing=True,
    )

    _scheduler.add_job(
        rollup_job,
        CronTrigger(minute="5"),
        id="rollup",
        name="Compute query rollups",
        replace_existing=True,
    )

    _scheduler.add_job(
        retention_job,
        CronTrigger(hour="3", minute="0"),
        id="retention",
        name="Cleanup old data",
        replace_existing=True,
    )

    _scheduler.add_job(
        precache_warming_job,
        IntervalTrigger(minutes=5),
        id="precache_warming",
        name="Warm cache with top domains",
        replace_existing=True,
    )

    _scheduler.add_job(
        scrape_local_recursor_metrics,
        IntervalTrigger(seconds=60),
        id="local_metrics",
        name="Collect local recursor metrics",
        replace_existing=True,
    )

    _scheduler.add_job(
        blocklist_schedule_job,
        IntervalTrigger(minutes=5),
        id="blocklist_schedule",
        name="Check blocklist schedules",
        replace_existing=True,
    )

    _scheduler.start()
    log.info("Background scheduler started")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("Background scheduler stopped")
