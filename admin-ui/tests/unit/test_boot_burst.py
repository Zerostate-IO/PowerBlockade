"""Unit tests for the readiness-gated boot warm burst (P9)."""

from __future__ import annotations

import threading
import time as real_time
from datetime import datetime, timedelta, timezone

import dns.message
import dns.rcode
import dns.rrset
import pytest
from sqlalchemy.orm import Session

from app.models.dns_query_event import DNSQueryEvent
from app.models.settings import DEFAULTS, set_setting
from app.services import boot_burst, precache
from app.services.boot_burst import (
    BACKOFF_BASE_S,
    PairWarmOutcome,
    QPSPacer,
    QnamePacer,
    _status_for,
    get_last_boot_burst,
    planned_burst_window_s,
    run_burst,
    wait_for_dns_readiness,
    warm_pair_ex,
)

QTYPE_A = 1
QTYPE_AAAA = 28


# =====================================================================
# Fakes
# =====================================================================
class FakeTimeline:
    """Virtual clock: sleep() records the wait and advances time instantly."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.waits: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += max(0.0, seconds)


class FakeSend:
    """Scripted send_fn: per-pair queues of outcomes, plus concurrency tracking."""

    def __init__(self, script: dict[tuple[str, int], list[PairWarmOutcome]] | None = None) -> None:
        self.script = {pair: list(outcomes) for pair, outcomes in (script or {}).items()}
        self.calls: list[tuple[str, int]] = []
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    def __call__(self, qname: str, qtype: int) -> PairWarmOutcome:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            self.calls.append((qname, qtype))
            queue = self.script.get((qname, qtype))
            if queue is None:
                return PairWarmOutcome(ttl=300, error=None)
            if len(queue) > 1:
                return queue.pop(0)
            return queue[0]
        finally:
            with self._lock:
                self._in_flight -= 1


def ok(ttl: int = 300) -> PairWarmOutcome:
    return PairWarmOutcome(ttl=ttl, error=None)


def err(error: str = "timed out") -> PairWarmOutcome:
    return PairWarmOutcome(ttl=None, error=error)


class FakeLockSession:
    """Stands in for the scheduler's DB session inside run_with_advisory_lock."""

    def __init__(self, acquired: bool, requested_locks: list[int]) -> None:
        self.acquired = acquired
        self.requested_locks = requested_locks

    def execute(self, stmt, params=None):
        requested = (params or {}).get("id")
        if requested is not None:
            self.requested_locks.append(requested)

        class _Result:
            @staticmethod
            def scalar() -> bool:
                return self.acquired

        return _Result()

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def make_lock_db(acquired: bool) -> tuple[list[list[int]], object]:
    """Build a SessionLocal stand-in recording every advisory lock id."""
    requested: list[list[int]] = []

    def factory():
        per_session: list[int] = []
        requested.append(per_session)
        return FakeLockSession(acquired, per_session)

    return requested, factory


def add_pair_events(session: Session, rows: list[tuple[str, int, int]]) -> None:
    """rows: (qname, qtype, repeat_count), all successful and non-blocked."""
    next_id = 1
    events = []
    now = datetime.now(timezone.utc)
    for qname, qtype, repeat in rows:
        for _ in range(repeat):
            events.append(
                DNSQueryEvent(
                    id=next_id,
                    ts=now - timedelta(minutes=5),
                    client_ip="192.168.1.100",
                    qname=qname,
                    qtype=qtype,
                    rcode=0,
                    blocked=False,
                    latency_ms=3,
                )
            )
            next_id += 1
    session.add_all(events)
    session.commit()


@pytest.fixture(autouse=True)
def reset_burst_state():
    precache._pair_ttl_cache.clear()
    with boot_burst._state_lock:
        boot_burst._last_result = None
    yield
    precache._pair_ttl_cache.clear()
    with boot_burst._state_lock:
        boot_burst._last_result = None


def fast_config(**overrides):
    """Engine-friendly settings: near-zero pacing, 1 worker default."""
    from app.services.boot_burst import BootBurstConfig

    values = dict(
        dns_server="127.0.0.1",
        dns_port=53,
        domain_count=1000,
        max_queries=2000,
        ignore_ttl=False,
        custom_refresh_minutes=60,
        qps=1_000_000.0,
        concurrency=1,
    )
    values.update(overrides)
    return BootBurstConfig(**values)


# =====================================================================
# Pacing math
# =====================================================================
class TestQPSPacer:
    def test_slots_spaced_at_least_one_over_qps(self):
        timeline = FakeTimeline()
        pacer = QPSPacer(qps=10.0, clock=timeline.clock, sleep=timeline.sleep)

        slots = [pacer.wait() for _ in range(5)]

        gaps = [b - a for a, b in zip(slots, slots[1:])]
        assert all(gap >= 1.0 / 10.0 - 1e-9 for gap in gaps)

    def test_jitter_only_adds_delay_ceiling_never_exceeded(self):
        """With random jitter the gaps stay within [1/qps, 1/qps * 1.2]."""
        timeline = FakeTimeline()
        pacer = QPSPacer(
            qps=10.0, jitter_ratio=0.10, clock=timeline.clock, sleep=timeline.sleep
        )

        slots = [pacer.wait() for _ in range(50)]

        gaps = [b - a for a, b in zip(slots, slots[1:])]
        assert all(gap >= 0.1 - 1e-9 for gap in gaps)
        assert all(gap <= 0.1 * 1.2 + 1e-9 for gap in gaps)

    def test_zero_qps_rejected(self):
        with pytest.raises(ValueError):
            QPSPacer(qps=0.0)


class TestQnamePacer:
    def test_first_send_to_qname_is_immediate(self):
        timeline = FakeTimeline()
        pacer = QnamePacer(0.2, clock=timeline.clock, sleep=timeline.sleep)

        pacer.wait("example.com")

        assert timeline.waits == []

    def test_same_qname_spaced_by_min_interval(self):
        timeline = FakeTimeline()
        pacer = QnamePacer(0.2, clock=timeline.clock, sleep=timeline.sleep)

        pacer.wait("example.com")
        pacer.wait("example.com")

        assert len(timeline.waits) == 1
        assert timeline.waits[0] == pytest.approx(0.2)

    def test_different_qnames_not_delayed_by_each_other(self):
        timeline = FakeTimeline()
        pacer = QnamePacer(0.2, clock=timeline.clock, sleep=timeline.sleep)

        pacer.wait("a.example.com")
        pacer.wait("b.example.com")

        assert timeline.waits == []


class TestBurstWindow:
    def test_window_is_queries_spread_over_qps(self):
        assert planned_burst_window_s(2000, 50.0) == 40.0

    def test_zero_qps_rejected(self):
        with pytest.raises(ValueError):
            planned_burst_window_s(10, 0.0)


# =====================================================================
# Burst engine
# =====================================================================
class TestRunBurst:
    def test_happy_path_counts_and_records_ttl_cache(self):
        timeline = FakeTimeline()
        send = FakeSend()

        stats = run_burst(
            [("a.example.com", QTYPE_A), ("b.example.com", QTYPE_AAAA)],
            send_fn=send,
            clock=timeline.clock,
            sleep_fn=timeline.sleep,
        )

        assert stats.attempted_pairs == 2
        assert stats.queries_sent == 2
        assert stats.succeeded == 2
        assert stats.failed == 0
        assert stats.top_failures == []
        assert precache._pair_ttl_cache[("a.example.com", QTYPE_A)].ttl == 300

    def test_duplicate_pairs_are_deduped(self):
        timeline = FakeTimeline()
        send = FakeSend()

        stats = run_burst(
            [("a.example.com", QTYPE_A)] * 3,
            send_fn=send,
            clock=timeline.clock,
            sleep_fn=timeline.sleep,
        )

        assert stats.attempted_pairs == 1
        assert send.calls == [("a.example.com", QTYPE_A)]

    def test_retry_with_exponential_backoff_then_success(self):
        timeline = FakeTimeline()
        send = FakeSend({("a.example.com", QTYPE_A): [err("timed out"), err("timed out"), ok()]})

        stats = run_burst(
            [("a.example.com", QTYPE_A)],
            send_fn=send,
            clock=timeline.clock,
            sleep_fn=timeline.sleep,
        )

        assert stats.succeeded == 1
        assert stats.queries_sent == 3  # initial + 2 retries
        assert BACKOFF_BASE_S in timeline.waits  # 0.5s after attempt 1
        assert BACKOFF_BASE_S * 2 in timeline.waits  # 1.0s after attempt 2

    def test_exhausted_retries_report_failure_and_error(self):
        timeline = FakeTimeline()
        send = FakeSend({("a.example.com", QTYPE_A): [err("rcode 2")]})

        stats = run_burst(
            [("a.example.com", QTYPE_A)],
            send_fn=send,
            clock=timeline.clock,
            sleep_fn=timeline.sleep,
        )

        assert stats.succeeded == 0
        assert stats.failed == 1
        assert stats.queries_sent == 3  # MAX_RETRIES=2 -> 3 attempts
        failure = stats.top_failures[0]
        assert failure["pair"] == "a.example.com/A"
        assert failure["attempts"] == 3
        assert failure["error"] == "rcode 2"

    def test_failed_pairs_are_not_recorded_in_ttl_cache(self):
        timeline = FakeTimeline()
        send = FakeSend({("a.example.com", QTYPE_A): [err()]})

        run_burst([("a.example.com", QTYPE_A)], send_fn=send, clock=timeline.clock, sleep_fn=timeline.sleep)

        assert ("a.example.com", QTYPE_A) not in precache._pair_ttl_cache

    def test_concurrency_is_bounded_by_workers(self):
        # Real (tiny) sleeps so worker overlap is observable.
        class SlowSend:
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self.in_flight = 0
                self.max_in_flight = 0

            def __call__(self, qname: str, qtype: int) -> PairWarmOutcome:
                with self._lock:
                    self.in_flight += 1
                    self.max_in_flight = max(self.max_in_flight, self.in_flight)
                real_time.sleep(0.005)
                with self._lock:
                    self.in_flight -= 1
                return ok()

        slow = SlowSend()
        pairs = [(f"n{i}.example.com", QTYPE_A) for i in range(16)]

        stats = run_burst(
            pairs,
            send_fn=slow,
            qps=100_000.0,  # pacing effectively off; the worker bound is under test
            concurrency=4,
            qname_min_interval_s=0.0,
        )

        assert stats.succeeded == 16
        assert 1 < slow.max_in_flight <= 4

    def test_empty_pair_list_is_a_no_op(self):
        stats = run_burst([], send_fn=FakeSend())

        assert stats.attempted_pairs == 0
        assert stats.queries_sent == 0


class TestStatusDerivation:
    def test_all_ok_completed(self):
        assert _status_for(_stats(failed=0, succeeded=5), 5) == "completed"

    def test_some_failed_partial(self):
        assert _status_for(_stats(failed=1, succeeded=4), 5) == "partial"

    def test_all_failed_failed(self):
        assert _status_for(_stats(failed=5, succeeded=0), 5) == "failed"


def _stats(**overrides) -> object:
    from app.services.boot_burst import BurstStats

    values = dict(attempted_pairs=5, queries_sent=5, succeeded=5, failed=0, max_concurrency=1)
    values.update(overrides)
    return BurstStats(**values)


class TestWarmPairExDetail:
    def test_servfail_reports_rcode_error(self, monkeypatch):
        def servfail(query, *args, **kwargs):
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.SERVFAIL)
            return response

        monkeypatch.setattr("dns.query.udp", servfail)

        outcome = warm_pair_ex("x.example.com", QTYPE_A, dns_server="127.0.0.1", port=53)

        assert outcome.ttl is None
        assert outcome.error == "rcode 2"

    def test_success_reports_ttl(self, monkeypatch):
        def answer(query, *args, **kwargs):
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.NOERROR)
            response.answer.append(
                dns.rrset.from_text("x.example.com.", 240, "IN", "A", "192.0.2.1")
            )
            return response

        monkeypatch.setattr("dns.query.udp", answer)

        outcome = warm_pair_ex("x.example.com", QTYPE_A, dns_server="127.0.0.1", port=53)

        assert outcome == PairWarmOutcome(ttl=240, error=None)


# =====================================================================
# Readiness gate
# =====================================================================
class TestReadiness:
    def test_ready_when_both_probes_pass_first_round(self):
        timeline = FakeTimeline()
        dns_calls, rec_calls = [], []

        ready = wait_for_dns_readiness(
            "dnsdist",
            53,
            "http://recursor:8082",
            timeout_s=10,
            poll_interval_s=2,
            dns_probe=lambda: (dns_calls.append(1), True)[1],
            recursor_probe=lambda: (rec_calls.append(1), True)[1],
            clock=timeline.clock,
            sleep_fn=timeline.sleep,
        )

        assert ready is True
        assert len(dns_calls) == 1
        assert len(rec_calls) == 1

    def test_times_out_bounded_when_dns_edge_never_answers(self):
        timeline = FakeTimeline()
        attempts = []

        ready = wait_for_dns_readiness(
            "dnsdist",
            53,
            "http://recursor:8082",
            timeout_s=6,
            poll_interval_s=2,
            dns_probe=lambda: (attempts.append("dns"), False)[1],
            recursor_probe=lambda: True,
            clock=timeline.clock,
            sleep_fn=timeline.sleep,
        )

        assert ready is False
        assert len(attempts) == 4  # t=0, 2, 4, 6
        assert timeline.waits == [2.0, 2.0, 2.0]  # no sleep past the deadline

    def test_unconfigured_recursor_api_is_not_required(self):
        timeline = FakeTimeline()

        ready = wait_for_dns_readiness(
            "dnsdist",
            53,
            "",
            timeout_s=2,
            dns_probe=lambda: True,
            recursor_probe=None,  # falls back to probe_recursor_api("")
            clock=timeline.clock,
            sleep_fn=timeline.sleep,
        )

        assert ready is True

    def test_probe_dns_edge_requires_a_response(self, monkeypatch):
        from app.services.boot_burst import probe_dns_edge

        def no_answer(query, *args, **kwargs):
            raise TimeoutError("the DNS operation timed out")

        monkeypatch.setattr("dns.query.udp", no_answer)
        assert probe_dns_edge("127.0.0.1", 53) is False

        def answers(query, *args, **kwargs):
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.SERVFAIL)
            return response

        monkeypatch.setattr("dns.query.udp", answers)
        assert probe_dns_edge("127.0.0.1", 53) is True

    def test_timeout_is_logged_as_warning(self, caplog):
        timeline = FakeTimeline()

        with caplog.at_level("WARNING", logger="app.services.boot_burst"):
            wait_for_dns_readiness(
                "dnsdist",
                53,
                "http://recursor:8082",
                timeout_s=1,
                poll_interval_s=1,
                dns_probe=lambda: False,
                recursor_probe=lambda: True,
                clock=timeline.clock,
                sleep_fn=timeline.sleep,
            )

        assert any("NOT ready" in record.message for record in caplog.records)


# =====================================================================
# Advisory-lock coordination (no double-fire with the periodic job)
# =====================================================================
class TestCoordination:
    def test_boot_burst_shares_the_periodic_job_lock_id(self, sync_db_session, monkeypatch):
        requested, lock_factory = make_lock_db(acquired=True)
        monkeypatch.setattr("app.services.scheduler.SessionLocal", lock_factory)
        monkeypatch.setattr("app.services.boot_burst.SessionLocal", lambda: sync_db_session)
        monkeypatch.setattr("app.services.precache.SessionLocal", lambda: sync_db_session)

        boot_burst._boot_burst_locked(fast_config())
        precache.precache_warming_job()

        assert len(requested) == 2
        boot_lock_ids, job_lock_ids = requested
        # Each session records the try-lock and its matching unlock.
        assert set(boot_lock_ids) == set(job_lock_ids)
        assert len(set(boot_lock_ids)) == 1

    def test_burst_body_does_not_run_when_lock_held(self, monkeypatch):
        _, lock_factory = make_lock_db(acquired=False)

        def inner_must_not_run():
            raise AssertionError("burst body ran while the lock was held")

        monkeypatch.setattr("app.services.scheduler.SessionLocal", lock_factory)
        monkeypatch.setattr(
            "app.services.boot_burst.SessionLocal", inner_must_not_run
        )

        result = boot_burst._boot_burst_locked(fast_config())

        assert result is None

    def test_entry_records_skipped_lock_when_periodic_job_wins(
        self, sync_db_session, monkeypatch
    ):
        _, lock_factory = make_lock_db(acquired=False)
        monkeypatch.setattr("app.services.scheduler.SessionLocal", lock_factory)
        monkeypatch.setattr("app.services.boot_burst.SessionLocal", lambda: sync_db_session)
        monkeypatch.setattr(
            "app.services.boot_burst.wait_for_dns_readiness",
            lambda *a, **k: True,
        )

        boot_burst._boot_burst_entry()

        summary = get_last_boot_burst()
        assert summary is not None
        assert summary["status"] == "skipped-lock"
        assert "advisory lock" in summary["reason"]


# =====================================================================
# Entry orchestration and partial-failure reporting
# =====================================================================
class TestBootBurstEntry:
    @pytest.fixture
    def wired_entry(self, sync_db_session, monkeypatch):
        """Entry wired to sqlite + a free advisory lock; readiness faked."""

        def _wire(send=None):
            _, lock_factory = make_lock_db(acquired=True)
            monkeypatch.setattr("app.services.scheduler.SessionLocal", lock_factory)
            monkeypatch.setattr("app.services.boot_burst.SessionLocal", lambda: sync_db_session)
            monkeypatch.setattr(
                "app.services.boot_burst.wait_for_dns_readiness",
                lambda *a, **k: True,
            )
            # Keep the burst fast: pacing near-zero, backoff tiny.
            monkeypatch.setattr(
                "app.services.boot_burst.run_burst",
                _fast_run_burst(send),
            )
            return sync_db_session

        return _wire

    def test_partial_failure_is_reported_never_silent(self, wired_entry, caplog):
        db = wired_entry(
            send=FakeSend({("bad.example.com", QTYPE_A): [err("rcode 2")]})
        )
        add_pair_events(
            db,
            [
                ("good1.example.com", QTYPE_A, 3),
                ("good2.example.com", QTYPE_AAAA, 2),
                ("bad.example.com", QTYPE_A, 1),
            ],
        )

        with caplog.at_level("WARNING", logger="app.services.boot_burst"):
            boot_burst._boot_burst_entry()

        summary = get_last_boot_burst()
        assert summary is not None
        assert summary["status"] == "partial"
        assert summary["candidates"] == 3
        assert summary["succeeded"] == 2
        assert summary["failed"] == 1
        assert summary["top_failures"][0]["pair"] == "bad.example.com/A"
        assert any(
            "Boot warm burst partial" in record.message and "bad.example.com" in record.message
            for record in caplog.records
        )

    def test_recently_warmed_pairs_are_skipped(self, wired_entry):
        db = wired_entry(send=FakeSend())
        add_pair_events(
            db,
            [
                ("fresh.example.com", QTYPE_A, 5),
                ("due.example.com", QTYPE_A, 4),
            ],
        )
        # P7 TTL cache says fresh.example.com was just warmed (TTL 3600).
        precache.record_warmed_pair("fresh.example.com", QTYPE_A, 3600)

        boot_burst._boot_burst_entry()

        summary = get_last_boot_burst()
        assert summary is not None
        assert summary["status"] == "completed"
        assert summary["skipped_fresh"] == 1
        assert summary["attempted_pairs"] == 1
        assert summary["succeeded"] == 1

    def test_per_pass_ceiling_caps_sends_without_inflating_fresh_skips(
        self, wired_entry
    ):
        db = wired_entry(send=FakeSend())
        add_pair_events(
            db,
            [
                ("fresh.example.com", QTYPE_A, 12),
                ("due1.example.com", QTYPE_A, 9),
                ("due2.example.com", QTYPE_A, 6),
            ],
        )
        precache.record_warmed_pair("fresh.example.com", QTYPE_A, 3600)
        set_setting(db, "precache_max_queries_per_pass", "1")

        boot_burst._boot_burst_entry()

        summary = get_last_boot_burst()
        assert summary is not None
        assert summary["status"] == "completed"
        assert summary["candidates"] == 3
        # Only the TTL-fresh pair counts as skipped: the pair cut off by
        # the per-pass ceiling is a policy cap, not freshness.
        assert summary["skipped_fresh"] == 1
        assert summary["attempted_pairs"] == 1
        assert summary["succeeded"] == 1

    def test_unready_stack_records_unready_and_sends_nothing(
        self, sync_db_session, monkeypatch
    ):
        _, lock_factory = make_lock_db(acquired=True)
        monkeypatch.setattr("app.services.scheduler.SessionLocal", lock_factory)
        monkeypatch.setattr("app.services.boot_burst.SessionLocal", lambda: sync_db_session)
        monkeypatch.setattr(
            "app.services.boot_burst.wait_for_dns_readiness",
            lambda *a, **k: False,
        )
        lock_calls: list[object] = []

        def locked_must_not_run(config):
            lock_calls.append(config)
            raise AssertionError("burst ran without readiness")

        monkeypatch.setattr("app.services.boot_burst._boot_burst_locked", locked_must_not_run)

        boot_burst._boot_burst_entry()

        assert lock_calls == []
        summary = get_last_boot_burst()
        assert summary is not None
        assert summary["status"] == "unready"
        assert summary["queries_sent"] == 0

    def test_disabled_setting_skips_everything(self, sync_db_session, monkeypatch):
        set_setting(sync_db_session, "precache_boot_burst_enabled", "false")
        _, lock_factory = make_lock_db(acquired=True)
        monkeypatch.setattr("app.services.scheduler.SessionLocal", lock_factory)
        monkeypatch.setattr("app.services.boot_burst.SessionLocal", lambda: sync_db_session)
        monkeypatch.setattr(
            "app.services.boot_burst.wait_for_dns_readiness",
            lambda *a, **k: True,
        )

        def locked_must_not_run(config):
            raise AssertionError("burst ran while disabled")

        monkeypatch.setattr("app.services.boot_burst._boot_burst_locked", locked_must_not_run)

        boot_burst._boot_burst_entry()

        summary = get_last_boot_burst()
        assert summary is not None
        assert summary["status"] == "disabled"


def _fast_run_burst(send):
    """run_burst with near-zero pacing/backoff for entry-level tests.

    A plain wrapper (NOT functools.partial): on Python 3.14+ keyword
    arguments at the call site override partial-bound keywords, so a
    partial would silently lose send_fn/qps to _boot_burst_locked's call
    and leak real network sends into unit tests.
    """

    if send is None:
        send = FakeSend()

    def _run(pairs, **_call_site_overrides):
        return run_burst(
            pairs,
            send_fn=send,
            qps=1_000_000.0,
            concurrency=4,
            max_retries=0,
            backoff_base_s=0.0,
            qname_min_interval_s=0.0,
        )

    return _run


# =====================================================================
# Settings
# =====================================================================
class TestBootBurstSettings:
    def test_defaults(self, sync_db_session):
        from app.models.settings import (
            get_precache_boot_burst_concurrency,
            get_precache_boot_burst_enabled,
            get_precache_boot_burst_qps,
        )

        assert DEFAULTS["precache_boot_burst_enabled"] == "true"
        assert DEFAULTS["precache_boot_burst_concurrency"] == "8"
        assert DEFAULTS["precache_boot_burst_qps"] == "50"
        assert get_precache_boot_burst_enabled(sync_db_session) is True
        assert get_precache_boot_burst_concurrency(sync_db_session) == 8
        assert get_precache_boot_burst_qps(sync_db_session) == 50.0

    def test_concurrency_clamped(self, sync_db_session):
        from app.models.settings import get_precache_boot_burst_concurrency

        set_setting(sync_db_session, "precache_boot_burst_concurrency", "0")
        assert get_precache_boot_burst_concurrency(sync_db_session) == 1
        set_setting(sync_db_session, "precache_boot_burst_concurrency", "999")
        assert get_precache_boot_burst_concurrency(sync_db_session) == 64

    def test_qps_clamped(self, sync_db_session):
        from app.models.settings import get_precache_boot_burst_qps

        set_setting(sync_db_session, "precache_boot_burst_qps", "0.5")
        assert get_precache_boot_burst_qps(sync_db_session) == 1.0
        set_setting(sync_db_session, "precache_boot_burst_qps", "5000")
        assert get_precache_boot_burst_qps(sync_db_session) == 1000.0
