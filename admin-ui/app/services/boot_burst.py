"""Readiness-gated boot warm burst (P9).

After a stack restart every cache layer is cold while clients keep asking,
so p99 latency and hit ratios are at their worst exactly when the stack
comes back up. This module recovers cache heat fast, WITHOUT harming
interactive traffic: an unpaced full-recursion flood at boot would compete
with real client queries for the recursor's outgoing slots.

Flow (all in a daemon thread, never blocking app startup or serving):

1. ``start_boot_burst()`` is called from the app lifespan after the
   scheduler starts. It spawns ``_boot_burst_entry`` in a background
   thread.
2. The entry reads settings, then ``wait_for_dns_readiness()`` polls
   (bounded) until BOTH the dnsdist edge answers a DNS probe AND the
   recursor web API (``RECURSOR_API_URL``) answers HTTP. An unreachable
   stack after the bounded wait means NO burst -- failed queries would
   just add load for nothing.
3. ``_boot_burst_locked()`` runs under the SAME advisory lock as the
   scheduled ``precache_warming_job`` (``run_with_advisory_lock``), so a
   boot burst and a periodic pass can never run concurrently. If the
   periodic job holds the lock, the burst records a ``skipped-lock``
   result instead of doubling up.
4. ``run_burst()`` warms the due top pairs with safety rails: bounded
   worker concurrency, a hard QPS ceiling (jitter only ever ADDS delay),
   per-qname spacing, dedup, P7 per-pair TTL freshness skipping,
   exponential backoff with a small retry budget, and a structured
   summary that is logged and kept for the /precache/boot-burst endpoint.

The per-pass query ceiling (``precache_max_queries_per_pass``) bounds how
many pairs one burst may touch; at ``precache_boot_burst_qps`` the burst
window is approximately ``pairs / qps`` seconds (2000 pairs at 50 qps =
~40s). The QPS number is a ceiling, not a target: recursion latency and
the worker bound keep the real rate at or below it.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence, cast

import dns.query
import dns.rdatatype
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.settings import (
    get_precache_boot_burst_concurrency,
    get_precache_boot_burst_enabled,
    get_precache_boot_burst_qps,
    get_precache_custom_refresh_minutes,
    get_precache_dns_port,
    get_precache_dns_server,
    get_precache_domain_count,
    get_precache_enabled,
    get_precache_ignore_ttl,
    get_precache_max_queries_per_pass,
)
from app.services.precache import (
    PairWarmOutcome,
    build_warm_query,
    get_pairs_needing_refresh,
    get_top_pairs_to_warm,
    record_warmed_pair,
    warm_pair_ex,
)
from app.services.scheduler import run_with_advisory_lock
from app.settings import get_settings

log = logging.getLogger(__name__)

# Must stay in sync with the scheduled precache_warming_job's lock name
# (app/services/precache.py). A unit test pins the two together by
# observing the lock ids both wrappers request.
WARMING_LOCK_JOB_NAME = "precache_warming"

# Readiness gate
BOOT_READINESS_TIMEOUT_S = 120.0
BOOT_READINESS_POLL_INTERVAL_S = 2.0
PROBE_TIMEOUT_S = 3.0

# Burst safety rails
DEFAULT_CONCURRENCY = 8
DEFAULT_QPS = 50.0
JITTER_RATIO = 0.10  # jitter only ever ADDS delay; the qps ceiling is never exceeded
QNAME_MIN_INTERVAL_S = 0.2  # spacing between different qtypes of one qname
MAX_RETRIES = 2  # 3 attempts total per pair
BACKOFF_BASE_S = 0.5  # retry backoff = base * 2**attempt (0.5s, 1.0s)
TOP_FAILURES_LIMIT = 10

Pair = tuple[str, int]


# =====================================================================
# Pacing gates
# =====================================================================
class QPSPacer:
    """Hard send-rate ceiling with additive jitter.

    ``wait()`` reserves the next send slot and sleeps until it. Slots are
    spaced 1/qps apart; each slot gap is stretched by up to
    ``2 * jitter_ratio`` (i.e. jitter between queries, e.g. ±10% around
    the +10% point) so the instantaneous rate NEVER exceeds ``qps`` --
    jitter can only delay a query, never advance it.
    """

    def __init__(
        self,
        qps: float,
        jitter_ratio: float = JITTER_RATIO,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[float, float], float] | None = None,
    ) -> None:
        if qps <= 0:
            raise ValueError(f"qps must be > 0, got {qps}")
        self._interval = 1.0 / qps
        self._jitter_ratio = jitter_ratio
        self._clock = clock
        self._sleep = sleep
        self._rng = rng or random.uniform
        self._lock = threading.Lock()
        self._next_slot = clock()

    def wait(self) -> float:
        """Reserve a slot and sleep until it; returns the planned send time."""
        with self._lock:
            slot = max(self._next_slot, self._clock())
            spread = 1.0 + self._rng(0.0, 2.0 * self._jitter_ratio)
            self._next_slot = slot + self._interval * spread
        delay = slot - self._clock()
        if delay > 0:
            self._sleep(delay)
        return slot


class QnamePacer:
    """Minimum interval between sends to the same qname.

    A and AAAA for one domain are different pairs on independent cadences,
    but they should not be sent back-to-back (or concurrently): each recurses
    the same qname upstream. The first send to a qname goes immediately.
    """

    def __init__(
        self,
        min_interval_s: float = QNAME_MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def wait(self, qname: str) -> None:
        with self._lock:
            last = self._last.get(qname)
            now = self._clock()
            at = now if last is None else max(last, now) + self._min_interval
            self._last[qname] = at
        delay = at - self._clock()
        if delay > 0:
            self._sleep(delay)


# =====================================================================
# Readiness gate
# =====================================================================
def probe_dns_edge(server: str, port: int, timeout_s: float = PROBE_TIMEOUT_S) -> bool:
    """True when the DNS edge answers at all (ANY rcode counts).

    Probes "." NS: the recursor answers from its built-in root hints, so
    the probe needs no upstream recursion and is not affected by RPZ
    filtering of real names. A SERVFAIL still proves dnsdist itself is
    listening; the separate recursor-API probe covers the recursor.
    """
    try:
        from app.services.precache import _resolve_dns_server

        query = build_warm_query(".", int(dns.rdatatype.NS))
        resolved = _resolve_dns_server(server)
        dns.query.udp(query, resolved, port=port, timeout=timeout_s)
        return True
    except Exception as e:
        log.debug(f"Boot burst DNS edge probe {server}:{port} failed: {e}")
        return False


def probe_recursor_api(url: str, timeout_s: float = PROBE_TIMEOUT_S) -> bool:
    """True when the recursor web API answers HTTP at all.

    Any HTTP status (even a 401 basic-auth challenge on /metrics) proves
    the recursor process is up. An empty URL means the API is not
    configured and is not treated as a readiness requirement (mirrors
    scrape_local_recursor_metrics).
    """
    if not url:
        return True
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(f"{url.rstrip('/')}/metrics")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            resp.read(1)
            return True
    except urllib.error.HTTPError:
        return True  # server answered; auth/404 still proves it is up
    except Exception as e:
        log.debug(f"Boot burst recursor API probe {url} failed: {e}")
        return False


def wait_for_dns_readiness(
    dns_server: str,
    dns_port: int,
    recursor_api_url: str,
    timeout_s: float = BOOT_READINESS_TIMEOUT_S,
    poll_interval_s: float = BOOT_READINESS_POLL_INTERVAL_S,
    dns_probe: Callable[[], bool] | None = None,
    recursor_probe: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Bounded wait until dnsdist AND the recursor are reachable.

    Returns True as soon as both probes pass; False after ``timeout_s``.
    Every outcome is logged (start at info, per-probe failures at debug,
    exhaustion at warning).
    """
    if dns_probe is None:

        def _probe_dns_default() -> bool:
            return probe_dns_edge(dns_server, dns_port)

        dns_probe = _probe_dns_default

    if recursor_probe is None:

        def _probe_recursor_default() -> bool:
            return probe_recursor_api(recursor_api_url)

        recursor_probe = _probe_recursor_default

    log.info(
        f"Boot warm burst: waiting up to {timeout_s:.0f}s for the DNS edge "
        f"({dns_server}:{dns_port}) and the recursor API "
        f"({recursor_api_url or 'not configured'}) to become reachable"
    )
    deadline = clock() + timeout_s
    attempts = 0
    while True:
        attempts += 1
        if dns_probe() and recursor_probe():
            log.info(f"Boot warm burst: DNS stack ready after {attempts} probe round(s)")
            return True
        if clock() >= deadline:
            log.warning(
                f"Boot warm burst: DNS stack NOT ready after {timeout_s:.0f}s "
                f"({attempts} probe rounds) - skipping the boot burst; the "
                f"periodic warming job will retry on its own cadence"
            )
            return False
        sleep_fn(poll_interval_s)


# =====================================================================
# Burst engine
# =====================================================================
@dataclass
class BurstStats:
    """Counters for one burst pass over a set of pairs."""

    attempted_pairs: int = 0
    queries_sent: int = 0  # every actual send, including retries
    succeeded: int = 0
    failed: int = 0
    max_concurrency: int = 0
    duration_s: float = 0.0
    top_failures: list[dict[str, object]] = field(default_factory=list)


@dataclass
class _PairResult:
    pair: Pair
    ok: bool
    attempts: int
    error: str | None


def _status_for(stats: BurstStats, attempted: int) -> str:
    if attempted == 0:
        return "completed"
    if stats.failed == 0:
        return "completed"
    if stats.succeeded == 0:
        return "failed"
    return "partial"


def _format_top_failures(failures: list[_PairResult]) -> list[dict[str, object]]:
    ranked = sorted(failures, key=lambda r: (-r.attempts, r.pair[0], r.pair[1]))
    out: list[dict[str, object]] = []
    for r in ranked[:TOP_FAILURES_LIMIT]:
        qname, qtype = r.pair
        out.append(
            {
                "pair": f"{qname}/{dns.rdatatype.to_text(cast(dns.rdatatype.RdataType, qtype))}",
                "attempts": r.attempts,
                "error": r.error or "no-successful-answer",
            }
        )
    return out


def run_burst(
    pairs: Sequence[Pair],
    *,
    send_fn: Callable[[str, int], PairWarmOutcome],
    qps: float = DEFAULT_QPS,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_retries: int = MAX_RETRIES,
    backoff_base_s: float = BACKOFF_BASE_S,
    qname_min_interval_s: float = QNAME_MIN_INTERVAL_S,
    jitter_ratio: float = JITTER_RATIO,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> BurstStats:
    """Warm ``pairs`` with all burst safety rails applied.

    ``send_fn`` performs one actual DNS send for a pair and returns its
    outcome; every call (retries included) passes through the QPS pacer,
    the per-qname pacer and the bounded worker pool. Successful pairs are
    recorded in P7's per-pair TTL cache (``record_warmed_pair``).
    """
    work = list(dict.fromkeys(pairs))  # dedup, ranked order preserved
    stats = BurstStats(attempted_pairs=len(work))
    if not work:
        return stats

    qps_pacer = QPSPacer(qps, jitter_ratio=jitter_ratio, clock=clock, sleep=sleep_fn)
    qname_pacer = QnamePacer(qname_min_interval_s, clock=clock, sleep=sleep_fn)
    send_lock = threading.Lock()
    in_flight = 0

    def _warm_one(pair: Pair) -> _PairResult:
        nonlocal in_flight
        qname, qtype = pair
        attempts = 0
        error: str | None = None
        for attempt in range(max_retries + 1):
            qps_pacer.wait()
            qname_pacer.wait(qname)
            attempts += 1
            with send_lock:
                in_flight += 1
                stats.max_concurrency = max(stats.max_concurrency, in_flight)
            try:
                outcome = send_fn(qname, qtype)
            finally:
                with send_lock:
                    in_flight -= 1
                    stats.queries_sent += 1
            if outcome.ttl is not None:
                record_warmed_pair(qname, qtype, outcome.ttl)
                return _PairResult(pair=pair, ok=True, attempts=attempts, error=None)
            error = outcome.error or error
            if attempt < max_retries:
                sleep_fn(backoff_base_s * (2**attempt))
        return _PairResult(pair=pair, ok=False, attempts=attempts, error=error)

    start = clock()
    workers = max(1, min(concurrency, len(work)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="boot-burst") as pool:
        results = list(pool.map(_warm_one, work))
    stats.duration_s = clock() - start

    failures = [r for r in results if not r.ok]
    stats.succeeded = len(results) - len(failures)
    stats.failed = len(failures)
    stats.top_failures = _format_top_failures(failures)
    return stats


def planned_burst_window_s(num_queries: int, qps: float) -> float:
    """Estimated burst duration: per-pass queries spread over the qps ceiling."""
    if qps <= 0:
        raise ValueError(f"qps must be > 0, got {qps}")
    return num_queries / qps


# =====================================================================
# Boot orchestration
# =====================================================================
@dataclass
class BootBurstResult:
    """Structured summary of one boot burst attempt.

    Kept for the /precache/boot-burst endpoint. A burst that sent queries
    and had failures is NEVER reported as simply "warm": status is
    ``partial`` or ``failed`` and ``top_failures`` lists the worst pairs.
    """

    status: (
        str  # completed | partial | failed | no-pairs | skipped-lock | unready | disabled | error
    )
    reason: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_s: float = 0.0
    candidates: int = 0  # deduped top pairs considered
    skipped_fresh: int = 0  # pairs skipped: P7 TTL cache says still fresh
    attempted_pairs: int = 0
    queries_sent: int = 0
    succeeded: int = 0
    failed: int = 0
    qps: float = 0.0
    concurrency: int = 0
    planned_window_s: float = 0.0
    top_failures: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(self.duration_s, 3),
            "candidates": self.candidates,
            "skipped_fresh": self.skipped_fresh,
            "attempted_pairs": self.attempted_pairs,
            "queries_sent": self.queries_sent,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "qps": self.qps,
            "concurrency": self.concurrency,
            "planned_window_s": round(self.planned_window_s, 1),
            "top_failures": self.top_failures,
        }


@dataclass
class BootBurstConfig:
    """Snapshot of the settings one burst runs with."""

    dns_server: str
    dns_port: int
    domain_count: int
    max_queries: int
    ignore_ttl: bool
    custom_refresh_minutes: int
    qps: float
    concurrency: int


_state_lock = threading.Lock()
_last_result: BootBurstResult | None = None


def get_last_boot_burst() -> dict[str, object] | None:
    with _state_lock:
        return _last_result.to_dict() if _last_result is not None else None


def _record_result(result: BootBurstResult) -> BootBurstResult:
    global _last_result
    with _state_lock:
        _last_result = result
    return result


def _log_summary(result: BootBurstResult) -> None:
    summary = (
        f"Boot warm burst {result.status}"
        f"{' (' + result.reason + ')' if result.reason else ''}: "
        f"{result.succeeded} warmed / {result.failed} failed / "
        f"{result.skipped_fresh} skipped-fresh, {result.queries_sent} queries sent "
        f"in {result.duration_s:.1f}s (qps<={result.qps:g}, workers={result.concurrency}, "
        f"planned window ~{result.planned_window_s:.0f}s)"
    )
    if result.failed > 0:
        failures = ", ".join(str(f["pair"]) for f in result.top_failures[:5])
        log.warning(f"{summary}; top failures: [{failures}]")
    else:
        log.info(summary)


def _load_config(db: Session) -> BootBurstConfig:
    return BootBurstConfig(
        dns_server=get_precache_dns_server(db),
        dns_port=get_precache_dns_port(db),
        domain_count=get_precache_domain_count(db),
        max_queries=get_precache_max_queries_per_pass(db),
        ignore_ttl=get_precache_ignore_ttl(db),
        custom_refresh_minutes=get_precache_custom_refresh_minutes(db),
        qps=get_precache_boot_burst_qps(db),
        concurrency=get_precache_boot_burst_concurrency(db),
    )


@run_with_advisory_lock(WARMING_LOCK_JOB_NAME)
def _boot_burst_locked(config: BootBurstConfig) -> BootBurstResult:
    """One burst pass, under the shared warming advisory lock.

    The decorator is the SAME lock (``precache_warming``) the scheduled
    periodic job takes, so the two can never run concurrently; whoever
    loses the race is skipped by the lock, not queued behind it.
    """
    started_wall = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        candidates = list(
            dict.fromkeys(get_top_pairs_to_warm(db, hours=24, limit=config.domain_count))
        )
        result = BootBurstResult(
            status="no-pairs",
            started_at=started_wall.isoformat(),
            qps=config.qps,
            concurrency=config.concurrency,
            candidates=len(candidates),
        )
        if not candidates:
            result.reason = "no (qname, qtype) pairs observed in the last 24h"
            result.finished_at = datetime.now(timezone.utc).isoformat()
            _log_summary(_record_result(result))
            return result

        # Respect P7's per-pair TTL cache: pairs warmed recently (e.g. by
        # another admin-ui instance that held the lock first) are skipped,
        # then the per-pass ceiling caps how many queries this burst sends.
        needing = get_pairs_needing_refresh(
            candidates, config.ignore_ttl, config.custom_refresh_minutes
        )
        # Only TTL-fresh pairs count as "skipped"; pairs cut off by the
        # per-pass ceiling are a policy cap, not freshness, and remain
        # visible as the attempted/candidates difference in the summary.
        result.skipped_fresh = len(candidates) - len(needing)
        due = needing[: config.max_queries]
        result.planned_window_s = planned_burst_window_s(len(due), config.qps)

        if not due:
            result.status = "completed"
            result.reason = "all candidate pairs still fresh"
            result.finished_at = datetime.now(timezone.utc).isoformat()
            _log_summary(_record_result(result))
            return result

        log.info(
            f"Boot warm burst: warming {len(due)}/{len(candidates)} pairs "
            f"(skipped {result.skipped_fresh} fresh) at <={config.qps:g} qps with "
            f"{config.concurrency} workers, window ~{result.planned_window_s:.0f}s"
        )
        try:
            stats = run_burst(
                due,
                send_fn=lambda qname, qtype: warm_pair_ex(
                    qname, qtype, dns_server=config.dns_server, port=config.dns_port
                ),
                qps=config.qps,
                concurrency=config.concurrency,
            )
        except Exception as e:
            # Never silently swallow a burst crash: record and log it as an
            # error result the endpoint can expose.
            result.status = "error"
            result.reason = f"burst engine failed: {e}"
            result.finished_at = datetime.now(timezone.utc).isoformat()
            log.error(f"Boot warm burst engine error: {e}")
            _record_result(result)
            return result
        result.status = _status_for(stats, stats.attempted_pairs)
        result.attempted_pairs = stats.attempted_pairs
        result.queries_sent = stats.queries_sent
        result.succeeded = stats.succeeded
        result.failed = stats.failed
        result.duration_s = stats.duration_s
        result.top_failures = stats.top_failures
        result.finished_at = datetime.now(timezone.utc).isoformat()
        _log_summary(_record_result(result))
        return result
    finally:
        db.close()


def _boot_burst_entry() -> None:
    """Daemon-thread entry point: settings -> readiness -> locked burst."""
    started_wall = datetime.now(timezone.utc).isoformat()
    try:
        db = SessionLocal()
        try:
            if not get_precache_enabled(db) or not get_precache_boot_burst_enabled(db):
                _log_summary(
                    _record_result(
                        BootBurstResult(
                            status="disabled",
                            reason="precache or boot burst disabled in settings",
                            started_at=started_wall,
                        )
                    )
                )
                return
            config = _load_config(db)
        finally:
            db.close()
    except Exception as e:
        log.error(f"Boot warm burst: could not load settings: {e}")
        _record_result(
            BootBurstResult(
                status="error", reason=f"settings load failed: {e}", started_at=started_wall
            )
        )
        return

    if not wait_for_dns_readiness(
        config.dns_server, config.dns_port, get_settings().recursor_api_url
    ):
        _log_summary(
            _record_result(
                BootBurstResult(
                    status="unready",
                    reason="dnsdist/recursor not reachable within the bounded wait",
                    started_at=started_wall,
                    qps=config.qps,
                    concurrency=config.concurrency,
                )
            )
        )
        return

    result = _boot_burst_locked(config)
    if result is None:
        # The advisory lock was held (periodic warming or another
        # admin-ui instance); the burst deliberately does NOT queue.
        _log_summary(
            _record_result(
                BootBurstResult(
                    status="skipped-lock",
                    reason="advisory lock held by the periodic warming job or another instance",
                    started_at=started_wall,
                    qps=config.qps,
                    concurrency=config.concurrency,
                )
            )
        )


def start_boot_burst() -> None:
    """Spawn the readiness-gated boot warm burst.

    Called from the app lifespan right after the scheduler starts. The
    burst runs in a daemon thread so app startup and request serving are
    never blocked by readiness waits, lock waits or slow queries.
    """
    thread = threading.Thread(target=_boot_burst_entry, name="precache-boot-burst", daemon=True)
    thread.start()
    log.debug("Boot warm burst thread started")
