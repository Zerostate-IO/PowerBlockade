from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.dns_query_event import DNSQueryEvent
from app.models.settings import (
    get_precache_custom_refresh_minutes,
    get_precache_domain_count,
    get_precache_enabled,
    get_precache_ignore_ttl,
)
from app.settings import get_settings

log = logging.getLogger(__name__)

BATCH_SIZE = 50
BATCH_DELAY_MS = 100


@dataclass
class WarmingResult:
    success: int
    failed: int
    total: int
    duration_ms: float


@dataclass
class DomainTTL:
    domain: str
    ttl: int
    last_warmed: datetime | None = None


_domain_ttl_cache: dict[str, DomainTTL] = {}


def get_top_domains_to_warm(db: Session, hours: int = 24, limit: int = 1000) -> list[str]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    results = (
        db.query(DNSQueryEvent.qname, sa.func.count(DNSQueryEvent.id).label("count"))
        .filter(
            DNSQueryEvent.ts >= since,
            DNSQueryEvent.blocked.is_(False),
            DNSQueryEvent.rcode == 0,
        )
        .group_by(DNSQueryEvent.qname)
        .order_by(sa.desc("count"))
        .limit(limit)
        .all()
    )

    return [r.qname for r in results]


def warm_domain(domain: str, dns_server: str = "127.0.0.1", port: int = 53) -> int | None:
    try:
        import dns.resolver

        resolver = dns.resolver.Resolver()
        resolver.nameservers = [dns_server]
        resolver.port = port
        resolver.lifetime = 5.0

        answer = resolver.resolve(domain, "A")
        ttl = answer.rrset.ttl if answer.rrset else 300
        return ttl
    except Exception as e:
        log.debug(f"Failed to warm {domain}: {e}")
        return None


def warm_cache(
    domains: list[str],
    dns_server: str = "127.0.0.1",
    port: int = 53,
    batch_size: int = BATCH_SIZE,
) -> WarmingResult:
    start_time = time.monotonic()
    success = 0
    failed = 0

    for i, domain in enumerate(domains):
        ttl = warm_domain(domain, dns_server, port)
        if ttl is not None:
            success += 1
            _domain_ttl_cache[domain] = DomainTTL(
                domain=domain,
                ttl=ttl,
                last_warmed=datetime.now(timezone.utc),
            )
        else:
            failed += 1

        if (i + 1) % batch_size == 0 and i + 1 < len(domains):
            time.sleep(BATCH_DELAY_MS / 1000.0)

    duration_ms = (time.monotonic() - start_time) * 1000
    log.info(f"Cache warming: {success}/{len(domains)} in {duration_ms:.0f}ms")
    return WarmingResult(
        success=success, failed=failed, total=len(domains), duration_ms=duration_ms
    )


def get_domains_needing_refresh(
    domains: list[str],
    ignore_ttl: bool = False,
    custom_refresh_minutes: int = 60,
) -> list[str]:
    now = datetime.now(timezone.utc)
    needs_refresh = []

    for domain in domains:
        cached = _domain_ttl_cache.get(domain)
        if cached is None or cached.last_warmed is None:
            needs_refresh.append(domain)
            continue

        if ignore_ttl:
            refresh_threshold = timedelta(minutes=custom_refresh_minutes)
        else:
            safety_margin = max(cached.ttl * 0.2, 30)
            refresh_threshold = timedelta(seconds=cached.ttl - safety_margin)

        age = now - cached.last_warmed
        if age >= refresh_threshold:
            needs_refresh.append(domain)

    return needs_refresh


def precache_warming_job() -> None:
    db = SessionLocal()
    try:
        if not get_precache_enabled(db):
            log.debug("Precache warming disabled")
            return

        settings = get_settings()
        recursor_url = settings.recursor_api_url or "http://recursor:8082"
        dns_host = recursor_url.replace("http://", "").replace("https://", "").split(":")[0]

        if dns_host in ("recursor", "localhost", "127.0.0.1"):
            dns_host = "127.0.0.1"

        domain_count = get_precache_domain_count(db)
        ignore_ttl = get_precache_ignore_ttl(db)
        custom_refresh = get_precache_custom_refresh_minutes(db)

        all_domains = get_top_domains_to_warm(db, hours=24, limit=domain_count)
        if not all_domains:
            log.info("No domains to warm")
            return

        domains_to_warm = get_domains_needing_refresh(all_domains, ignore_ttl, custom_refresh)

        if not domains_to_warm:
            log.debug(f"All {len(all_domains)} domains still fresh, skipping")
            return

        log.info(f"Warming {len(domains_to_warm)}/{len(all_domains)} domains (TTL-based refresh)")
        result = warm_cache(domains_to_warm, dns_server=dns_host, port=53)
        log.info(
            f"Precache warming completed: {result.success} warmed in {result.duration_ms:.0f}ms"
        )

    except Exception as e:
        log.error(f"Precache warming job failed: {e}")
    finally:
        db.close()


def get_precache_stats() -> dict:
    now = datetime.now(timezone.utc)
    cached_count = len(_domain_ttl_cache)
    fresh_count = 0
    expired_count = 0

    for info in _domain_ttl_cache.values():
        if info.last_warmed is None:
            expired_count += 1
            continue
        age = (now - info.last_warmed).total_seconds()
        if age < info.ttl:
            fresh_count += 1
        else:
            expired_count += 1

    return {
        "cached_domains": cached_count,
        "fresh": fresh_count,
        "expired": expired_count,
    }
