from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.dns_query_event import DNSQueryEvent
from app.models.settings import (
    get_precache_custom_refresh_minutes,
    get_precache_dns_port,
    get_precache_dns_server,
    get_precache_domain_count,
    get_precache_enabled,
    get_precache_ignore_ttl,
    get_precache_max_queries_per_pass,
)
from app.services.scheduler import run_with_advisory_lock

log = logging.getLogger(__name__)

BATCH_SIZE = 50
BATCH_DELAY_MS = 100

# Fallback refresh TTL when a NOERROR response carries no readable TTL at all
# (empty ANSWER and no SOA in AUTHORITY).
DEFAULT_FALLBACK_TTL = 300

# =====================================================================
# Cache-layering semantics (P7 warming upgrade)
#
# Warming queries go THROUGH the dnsdist edge (precache_dns_server /
# precache_dns_port, default dnsdist:53). That refreshes the EDGE layer:
# every warmed (qname, qtype) pair gets a dnsdist packet-cache entry that
# clients hit directly.
#
# A query that HITS the dnsdist packet cache never reaches the recursor, so
# an ordinary warm pass CANNOT by itself guarantee the inner recursor
# record/packet caches stay populated. The inner layer is maintained by:
#   * the recursor's own caches (populated whenever a warm query misses the
#     edge cache and is recursed), and
#   * the recursor's near-expiry revalidation / serve-stale behaviour.
# A separate recursor-side refresh experiment is planned to measure and,
# if needed, close that gap; it is out of scope for this module.
#
# See docs/performance/dns-caching-strategy.md ("Warming and the two cache
# layers").
# =====================================================================


@dataclass
class WarmingResult:
    success: int
    failed: int
    total: int
    duration_ms: float


@dataclass
class PairTTL:
    """TTL tracking for one observed (qname, qtype) pair.

    Tracked per PAIR, not per qname: example.com A (TTL 300) and example.com
    AAAA (TTL 60) must refresh on independent cadences, each governed by the
    shortest TTL observed for that pair (see warm_pair()).
    """

    qname: str
    qtype: int
    ttl: int
    last_warmed: datetime | None = None


_pair_ttl_cache: dict[tuple[str, int], PairTTL] = {}


def get_top_pairs_to_warm(
    db: Session, hours: int = 24, limit: int = 1000, max_queries: int | None = None
) -> list[tuple[str, int]]:
    """Top (qname, qtype) pairs to warm, ranked by per-pair query count.

    Selection window and success filter (same window as the previous
    per-qname selection):
      * observed at the dnsdist edge within the lookback window,
      * successful: rcode == 0 (NOERROR),
      * not blocked.

    NOTE on "answer-present": dns_query_events has no answer-count column,
    so NOERROR-with-no-answers (NODATA) pairs cannot be distinguished from
    pairs that returned records. rcode-0 is the best available proxy for
    "warming-positive"; NODATA pairs are still worth warming because their
    negative answers are cached too.

    ``max_queries``, when set, truncates the result to at most that many
    pairs (per-pass request ceiling, precache_max_queries_per_pass).
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    results = (
        db.query(
            DNSQueryEvent.qname,
            DNSQueryEvent.qtype,
            sa.func.count(DNSQueryEvent.id).label("count"),
        )
        .filter(
            DNSQueryEvent.ts >= since,
            DNSQueryEvent.blocked.is_(False),
            DNSQueryEvent.rcode == 0,
        )
        .group_by(DNSQueryEvent.qname, DNSQueryEvent.qtype)
        .order_by(sa.desc("count"))
        .limit(limit)
        .all()
    )

    pairs = [(r.qname, r.qtype) for r in results]
    if max_queries is not None:
        pairs = pairs[:max_queries]
    return pairs


def get_top_domains_to_warm(db: Session, hours: int = 24, limit: int = 1000) -> list[str]:
    """Unique qnames from the top pairs, in ranked order.

    Kept as a thin wrapper over the pair-based selection for consumers that
    only want a domain list (e.g. the node-sync precache-domains endpoint
    used by secondary nodes).
    """
    seen: set[str] = set()
    domains: list[str] = []
    for qname, _qtype in get_top_pairs_to_warm(db, hours=hours, limit=limit):
        if qname not in seen:
            seen.add(qname)
            domains.append(qname)
    return domains


def _resolve_dns_server(dns_server: str) -> str:
    """Resolve hostname to IP if needed (dnspython requires IP addresses)."""
    import socket

    try:
        socket.inet_aton(dns_server)
        return dns_server
    except socket.error:
        pass

    try:
        return socket.gethostbyname(dns_server)
    except socket.gaierror:
        return dns_server


def build_warm_query(qname: str, qtype: int):
    """Build the UDP query for an observed (qname, qtype) pair.

    dns.resolver.resolve() only supports a small set of "resolvable" types,
    so warming uses raw message construction: ANY observed qtype (A=1,
    AAAA=28, HTTPS=65, ...) is re-asked exactly as clients asked for it.
    Separate as a function so tests can assert query construction without
    touching the network.
    """
    import dns.message
    import dns.rdatatype

    # RdataType is an IntEnum: any observed qtype number is valid on the
    # wire, so cast instead of RdataType(qtype) (which rejects unknown
    # qtype values).
    rdtype = cast(dns.rdatatype.RdataType, qtype)
    return dns.message.make_query(qname, rdtype)


def _min_response_ttl(response) -> int | None:
    """Shortest TTL observable in a response, used for refresh cadence.

    ANSWER sections can carry several RRsets with different TTLs (CNAME
    chains, multi-record HTTPS answers); the shortest one governs when a
    cached entry can expire, so it is what the refresh cadence must respect.
    For NOERROR-with-no-answers (NODATA), fall back to the negative TTL from
    the SOA in AUTHORITY (min of SOA TTL and SOA.MINIMUM).
    """
    import dns.rdatatype

    ttls = [rrset.ttl for rrset in response.answer if rrset is not None]
    if not ttls:
        for rrset in response.authority:
            if rrset.rdtype == dns.rdatatype.SOA:
                soa = rrset[0]
                ttls.append(min(rrset.ttl, soa.minimum))
    if not ttls:
        return None
    return min(ttls)


def warm_pair(qname: str, qtype: int, dns_server: str = "127.0.0.1", port: int = 53) -> int | None:
    """Warm one observed (qname, qtype) pair through the configured edge.

    Default port is 53 (dnsdist edge), NOT recursor:5300 — warming goes
    through the dnsdist packet cache so the edge layer holds an entry for
    the exact (qname, qtype) clients asked for. See the layering notes at
    the top of this module: this refreshes the edge; the recursor's own
    caches handle the inner layer.

    Returns the shortest TTL observed in the response (drives refresh
    cadence), or None when the query failed or returned a non-NOERROR rcode.
    """
    try:
        import dns.query

        query = build_warm_query(qname, qtype)
        resolved_server = _resolve_dns_server(dns_server)
        response = dns.query.udp(query, resolved_server, port=port, timeout=5)

        if response.rcode() != 0:
            log.debug(f"Warm query for {qname}/{qtype} returned rcode {response.rcode()}")
            return None

        ttl = _min_response_ttl(response)
        if ttl is None:
            return DEFAULT_FALLBACK_TTL
        return ttl
    except Exception as e:
        log.debug(f"Failed to warm {qname}/{qtype}: {e}")
        return None


def warm_cache(
    pairs: list[tuple[str, int]],
    dns_server: str = "127.0.0.1",
    port: int = 53,
    batch_size: int = BATCH_SIZE,
) -> WarmingResult:
    """Warm the edge cache for a list of (qname, qtype) pairs.

    Queries go through the dnsdist edge (default :53, see warm_pair()).
    TTLs are tracked PER PAIR: each (qname, qtype) keeps the shortest TTL
    observed for that pair, so refresh cadence never outlives any TTL the
    pair has actually returned.
    """
    start_time = time.monotonic()
    success = 0
    failed = 0

    for i, (qname, qtype) in enumerate(pairs):
        ttl = warm_pair(qname, qtype, dns_server, port)
        if ttl is not None:
            success += 1
            key = (qname, qtype)
            now = datetime.now(timezone.utc)
            cached = _pair_ttl_cache.get(key)
            if cached is None:
                _pair_ttl_cache[key] = PairTTL(qname=qname, qtype=qtype, ttl=ttl, last_warmed=now)
            else:
                # Shortest TTL ever observed for this pair wins. Deliberately
                # conservative: a later longer TTL does not relax the cadence,
                # because the shorter entry lifetime was really observed.
                cached.ttl = min(cached.ttl, ttl)
                cached.last_warmed = now
        else:
            failed += 1

        if (i + 1) % batch_size == 0 and i + 1 < len(pairs):
            time.sleep(BATCH_DELAY_MS / 1000.0)

    duration_ms = (time.monotonic() - start_time) * 1000
    log.info(f"Cache warming: {success}/{len(pairs)} pairs in {duration_ms:.0f}ms")
    return WarmingResult(success=success, failed=failed, total=len(pairs), duration_ms=duration_ms)


def get_pairs_needing_refresh(
    pairs: list[tuple[str, int]],
    ignore_ttl: bool = False,
    custom_refresh_minutes: int = 60,
) -> list[tuple[str, int]]:
    """Filter pairs whose cached entry has (nearly) expired.

    Per-pair TTL-aware refresh (default): refresh at
    ``ttl - max(ttl * 0.2, 30s)`` using the SHORTEST TTL observed for that
    (qname, qtype) pair. With ``ignore_ttl`` a fixed interval applies.
    """
    now = datetime.now(timezone.utc)
    needs_refresh = []

    for pair in pairs:
        cached = _pair_ttl_cache.get(pair)
        if cached is None or cached.last_warmed is None:
            needs_refresh.append(pair)
            continue

        if ignore_ttl:
            refresh_threshold = timedelta(minutes=custom_refresh_minutes)
        else:
            safety_margin = max(cached.ttl * 0.2, 30)
            refresh_threshold = timedelta(seconds=cached.ttl - safety_margin)

        age = now - cached.last_warmed
        if age >= refresh_threshold:
            needs_refresh.append(pair)

    return needs_refresh


@run_with_advisory_lock("precache_warming")
def precache_warming_job() -> None:
    db = SessionLocal()
    try:
        if not get_precache_enabled(db):
            log.debug("Precache warming disabled")
            return

        dns_host = get_precache_dns_server(db)
        dns_port = get_precache_dns_port(db)
        domain_count = get_precache_domain_count(db)
        ignore_ttl = get_precache_ignore_ttl(db)
        custom_refresh = get_precache_custom_refresh_minutes(db)
        max_queries = get_precache_max_queries_per_pass(db)

        all_pairs = get_top_pairs_to_warm(db, hours=24, limit=domain_count)
        if not all_pairs:
            log.info("No (qname, qtype) pairs to warm")
            return

        # Per-pass request ceiling: never send more than max_queries warm
        # queries in one pass, regardless of how many pairs are due.
        pairs_to_warm = get_pairs_needing_refresh(all_pairs, ignore_ttl, custom_refresh)[
            :max_queries
        ]

        if not pairs_to_warm:
            log.debug(f"All {len(all_pairs)} pairs still fresh, skipping")
            return

        log.info(
            f"Warming {len(pairs_to_warm)}/{len(all_pairs)} (qname, qtype) pairs "
            f"(ceiling {max_queries}/pass, TTL-based refresh)"
        )
        result = warm_cache(pairs_to_warm, dns_server=dns_host, port=dns_port)
        log.info(
            f"Precache warming completed: {result.success} pairs warmed "
            f"in {result.duration_ms:.0f}ms"
        )

    except Exception as e:
        log.error(f"Precache warming job failed: {e}")
    finally:
        db.close()


def get_precache_stats() -> dict:
    now = datetime.now(timezone.utc)
    cached_count = len(_pair_ttl_cache)
    fresh_count = 0
    expired_count = 0
    by_qtype: dict[int, int] = {}

    for info in _pair_ttl_cache.values():
        by_qtype[info.qtype] = by_qtype.get(info.qtype, 0) + 1
        if info.last_warmed is None:
            expired_count += 1
            continue
        age = (now - info.last_warmed).total_seconds()
        if age < info.ttl:
            fresh_count += 1
        else:
            expired_count += 1

    return {
        "cached_pairs": cached_count,
        "fresh": fresh_count,
        "expired": expired_count,
        "by_qtype": by_qtype,
    }
