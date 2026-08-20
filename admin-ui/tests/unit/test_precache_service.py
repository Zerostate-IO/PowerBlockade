"""Unit tests for (qname, qtype) pair-based precache warming (P7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import dns.message
import dns.rcode
import dns.rrset
import pytest

from app.models.dns_query_event import DNSQueryEvent
from app.models.settings import (
    DEFAULTS,
    get_setting,
    set_setting,
)
from app.services import precache
from app.services.precache import (
    DEFAULT_FALLBACK_TTL,
    build_warm_query,
    get_pairs_needing_refresh,
    get_precache_stats,
    get_top_domains_to_warm,
    get_top_pairs_to_warm,
    warm_cache,
    warm_pair,
)

# Wire-format qtype numbers for common types.
QTYPE_A = 1
QTYPE_CNAME = 5
QTYPE_SOA = 6
QTYPE_AAAA = 28
QTYPE_HTTPS = 65


def add_events(session, now, rows):
    """Insert query events.

    rows: list of (qname, qtype, rcode, blocked, repeat_count).
    """
    events = []
    next_id = 1
    for qname, qtype, rcode, blocked, repeat in rows:
        for _ in range(repeat):
            events.append(
                DNSQueryEvent(
                    id=next_id,
                    ts=now - timedelta(minutes=5),
                    client_ip="192.168.1.100",
                    qname=qname,
                    qtype=qtype,
                    rcode=rcode,
                    blocked=blocked,
                    latency_ms=3,
                )
            )
            next_id += 1
    session.add_all(events)
    session.commit()


@pytest.fixture(autouse=True)
def clear_pair_ttl_cache():
    precache._pair_ttl_cache.clear()
    yield
    precache._pair_ttl_cache.clear()


class TestPairSelection:
    def test_groups_and_ranks_by_qname_qtype(self, sync_db_session):
        """Pairs are grouped and ranked by per-pair count, not per qname."""
        now = datetime.now(timezone.utc)
        add_events(
            sync_db_session,
            now,
            [
                ("a.example.com", QTYPE_A, 0, False, 5),
                ("a.example.com", QTYPE_AAAA, 0, False, 3),
                ("b.example.com", QTYPE_A, 0, False, 4),
                ("b.example.com", QTYPE_HTTPS, 0, False, 1),
            ],
        )

        pairs = get_top_pairs_to_warm(sync_db_session, hours=24)

        assert pairs == [
            ("a.example.com", QTYPE_A),
            ("b.example.com", QTYPE_A),
            ("a.example.com", QTYPE_AAAA),
            ("b.example.com", QTYPE_HTTPS),
        ]

    def test_excludes_blocked_and_nonzero_rcode(self, sync_db_session):
        now = datetime.now(timezone.utc)
        add_events(
            sync_db_session,
            now,
            [
                ("ok.example.com", QTYPE_A, 0, False, 2),
                ("blocked.example.com", QTYPE_A, 0, True, 10),
                ("nx.example.com", QTYPE_A, 3, False, 10),
                ("servfail.example.com", QTYPE_AAAA, 2, False, 10),
            ],
        )

        pairs = get_top_pairs_to_warm(sync_db_session, hours=24)

        assert pairs == [("ok.example.com", QTYPE_A)]

    def test_excludes_events_outside_window(self, sync_db_session):
        now = datetime.now(timezone.utc)
        session = sync_db_session
        session.add_all(
            [
                DNSQueryEvent(
                    id=1,
                    ts=now - timedelta(hours=25),
                    client_ip="192.168.1.100",
                    qname="stale.example.com",
                    qtype=QTYPE_A,
                    rcode=0,
                    blocked=False,
                ),
                DNSQueryEvent(
                    id=2,
                    ts=now - timedelta(hours=1),
                    client_ip="192.168.1.100",
                    qname="fresh.example.com",
                    qtype=QTYPE_AAAA,
                    rcode=0,
                    blocked=False,
                ),
            ]
        )
        session.commit()

        pairs = get_top_pairs_to_warm(session, hours=24)

        assert pairs == [("fresh.example.com", QTYPE_AAAA)]

    def test_limit_bounds_selection(self, sync_db_session):
        now = datetime.now(timezone.utc)
        add_events(
            sync_db_session,
            now,
            [
                ("a.example.com", QTYPE_A, 0, False, 3),
                ("b.example.com", QTYPE_A, 0, False, 2),
                ("c.example.com", QTYPE_A, 0, False, 1),
            ],
        )

        pairs = get_top_pairs_to_warm(sync_db_session, hours=24, limit=2)

        assert pairs == [("a.example.com", QTYPE_A), ("b.example.com", QTYPE_A)]

    def test_max_queries_ceiling_truncates(self, sync_db_session):
        """precache_max_queries_per_pass caps how many pairs one pass takes."""
        now = datetime.now(timezone.utc)
        add_events(
            sync_db_session,
            now,
            [(f"n{i}.example.com", QTYPE_A, 0, False, 10 - i) for i in range(5)],
        )

        pairs = get_top_pairs_to_warm(sync_db_session, hours=24, limit=100, max_queries=2)

        assert len(pairs) == 2
        assert pairs[0] == ("n0.example.com", QTYPE_A)
        assert pairs[1] == ("n1.example.com", QTYPE_A)

    def test_get_top_domains_dedupes_pairs_in_ranked_order(self, sync_db_session):
        now = datetime.now(timezone.utc)
        add_events(
            sync_db_session,
            now,
            [
                ("a.example.com", QTYPE_A, 0, False, 5),
                ("a.example.com", QTYPE_AAAA, 0, False, 3),
                ("b.example.com", QTYPE_A, 0, False, 4),
            ],
        )

        domains = get_top_domains_to_warm(sync_db_session, hours=24)

        assert domains == ["a.example.com", "b.example.com"]


class FakeUDP:
    """Stand-in for dns.query.udp that records queries and returns canned responses."""

    def __init__(self, response_for):
        # response_for: callable(query) -> dns.message.Message
        self.response_for = response_for
        self.queries: list[dns.message.Message] = []

    def __call__(self, query, *args, **kwargs):
        self.queries.append(query)
        return self.response_for(query)


def make_response(query, rcode=dns.rcode.NOERROR, answer=None, authority=None):
    response = dns.message.make_response(query)
    response.set_rcode(rcode)
    for rrset in answer or []:
        response.answer.append(rrset)
    for rrset in authority or []:
        response.authority.append(rrset)
    return response


class TestWarmQueryConstruction:
    def test_builds_query_with_observed_qtype_a(self):
        query = build_warm_query("example.com", QTYPE_A)

        question = query.question[0]
        assert str(question.name) == "example.com."
        assert question.rdtype == QTYPE_A

    def test_builds_query_with_observed_qtype_aaaa(self):
        query = build_warm_query("example.com", QTYPE_AAAA)

        assert query.question[0].rdtype == QTYPE_AAAA

    def test_builds_query_with_observed_qtype_https(self):
        """Arbitrary qtypes like HTTPS (65) must be askable, not just A."""
        query = build_warm_query("example.com", QTYPE_HTTPS)

        assert query.question[0].rdtype == QTYPE_HTTPS
        assert "HTTPS" in query.to_text()


class TestWarmPair:
    def test_sends_query_for_exact_pair_and_returns_ttl(self, monkeypatch):
        fake = FakeUDP(
            lambda q: make_response(
                q,
                answer=[dns.rrset.from_text("example.com.", 300, "IN", "A", "192.0.2.1")],
            )
        )
        monkeypatch.setattr("dns.query.udp", fake)

        ttl = warm_pair("example.com", QTYPE_A, dns_server="127.0.0.1", port=53)

        assert ttl == 300
        assert len(fake.queries) == 1
        sent = fake.queries[0]
        assert str(sent.question[0].name) == "example.com."
        assert sent.question[0].rdtype == QTYPE_A

    def test_returns_shortest_ttl_across_answer_rrsets(self, monkeypatch):
        """CNAME chains: the shortest TTL in the answer governs the cadence."""

        def response_for(q):
            if q.question[0].rdtype == QTYPE_A:
                return make_response(
                    q,
                    answer=[
                        dns.rrset.from_text(
                            "cname.example.com.", 600, "IN", "CNAME", "target.example.com."
                        ),
                        dns.rrset.from_text("target.example.com.", 60, "IN", "A", "192.0.2.10"),
                    ],
                )
            return make_response(
                q, answer=[dns.rrset.from_text("example.com.", 300, "IN", "AAAA", "2001:db8::1")]
            )

        fake = FakeUDP(response_for)
        monkeypatch.setattr("dns.query.udp", fake)

        assert warm_pair("cname.example.com", QTYPE_A) == 60
        assert warm_pair("example.com", QTYPE_AAAA) == 300

    def test_nodata_uses_soa_negative_ttl(self, monkeypatch):
        """NOERROR with no answers: negative TTL from SOA minimum (and SOA TTL)."""
        soa = dns.rrset.from_text(
            "example.com.",
            900,
            "IN",
            "SOA",
            "ns.example.com. hostmaster.example.com. 1 300 300 1200 300",
        )
        fake = FakeUDP(lambda q: make_response(q, authority=[soa]))
        monkeypatch.setattr("dns.query.udp", fake)

        ttl = warm_pair("nodata.example.com", QTYPE_AAAA)

        assert ttl == 300

    def test_nonzero_rcode_returns_none(self, monkeypatch):
        fake = FakeUDP(lambda q: make_response(q, rcode=dns.rcode.NXDOMAIN))
        monkeypatch.setattr("dns.query.udp", fake)

        assert warm_pair("nx.example.com", QTYPE_A) is None

    def test_fallback_ttl_when_no_ttl_information(self, monkeypatch):
        fake = FakeUDP(lambda q: make_response(q))
        monkeypatch.setattr("dns.query.udp", fake)

        assert warm_pair("empty.example.com", QTYPE_A) == DEFAULT_FALLBACK_TTL


class TestTTLPerPairTracking:
    @staticmethod
    def udp_returning(ttl_by_pair):
        def response_for(q):
            qtype = q.question[0].rdtype
            qname = str(q.question[0].name)
            ttl = ttl_by_pair.get((qname, qtype), 300)
            if qtype == QTYPE_AAAA:
                rr = dns.rrset.from_text(qname, ttl, "IN", "AAAA", "2001:db8::1")
            else:
                rr = dns.rrset.from_text(qname, ttl, "IN", "A", "192.0.2.1")
            return make_response(q, answer=[rr])

        return FakeUDP(response_for)

    def test_ttl_tracked_per_pair_not_per_qname(self, monkeypatch):
        monkeypatch.setattr(
            "dns.query.udp",
            self.udp_returning({("example.com.", QTYPE_A): 300, ("example.com.", QTYPE_AAAA): 60}),
        )

        result = warm_cache(
            [("example.com", QTYPE_A), ("example.com", QTYPE_AAAA)],
            dns_server="127.0.0.1",
            port=53,
        )

        assert result.success == 2
        assert precache._pair_ttl_cache[("example.com", QTYPE_A)].ttl == 300
        assert precache._pair_ttl_cache[("example.com", QTYPE_AAAA)].ttl == 60

        stats = get_precache_stats()
        assert stats["cached_pairs"] == 2
        assert stats["by_qtype"] == {QTYPE_A: 1, QTYPE_AAAA: 1}

    def test_refresh_cadence_respects_shortest_ttl_per_pair(self, monkeypatch):
        monkeypatch.setattr(
            "dns.query.udp",
            self.udp_returning({("example.com.", QTYPE_A): 300, ("example.com.", QTYPE_AAAA): 60}),
        )
        pairs = [("example.com", QTYPE_A), ("example.com", QTYPE_AAAA)]
        warm_cache(pairs, dns_server="127.0.0.1", port=53)

        # Rewind last_warmed 50s: A refreshes at 300-max(60,30)=240s (fresh),
        # AAAA refreshes at 60-max(12,30)=30s (due).
        warmed_at = datetime.now(timezone.utc) - timedelta(seconds=50)
        for info in precache._pair_ttl_cache.values():
            info.last_warmed = warmed_at

        due = get_pairs_needing_refresh(pairs)

        assert due == [("example.com", QTYPE_AAAA)]

    def test_unwarmed_pairs_always_due(self):
        assert get_pairs_needing_refresh([("never.example.com", QTYPE_A)]) == [
            ("never.example.com", QTYPE_A)
        ]

    def test_shorter_observed_ttl_tightens_cadence(self, monkeypatch):
        """A pair that once returned a shorter TTL keeps the faster cadence."""
        fake = self.udp_returning({("example.com.", QTYPE_A): 300})
        monkeypatch.setattr("dns.query.udp", fake)
        warm_cache([("example.com", QTYPE_A)], dns_server="127.0.0.1", port=53)
        assert precache._pair_ttl_cache[("example.com", QTYPE_A)].ttl == 300

        fake.response_for = self.udp_returning({("example.com.", QTYPE_A): 60}).response_for
        warm_cache([("example.com", QTYPE_A)], dns_server="127.0.0.1", port=53)

        assert precache._pair_ttl_cache[("example.com", QTYPE_A)].ttl == 60

    def test_ignore_ttl_uses_fixed_interval(self, monkeypatch):
        monkeypatch.setattr("dns.query.udp", self.udp_returning({("example.com.", QTYPE_A): 86400}))
        pairs = [("example.com", QTYPE_A)]
        warm_cache(pairs, dns_server="127.0.0.1", port=53)

        # 90s old: far fresher than the 24h TTL, but ignore_ttl refreshes on
        # the fixed custom interval (1 minute here).
        for info in precache._pair_ttl_cache.values():
            info.last_warmed = datetime.now(timezone.utc) - timedelta(seconds=90)

        due = get_pairs_needing_refresh(pairs, ignore_ttl=True, custom_refresh_minutes=1)

        assert due == pairs


class TestSettingsDefaults:
    def test_defaults_point_warming_at_dnsdist_edge(self):
        assert DEFAULTS["precache_dns_server"] == "dnsdist"
        assert DEFAULTS["precache_dns_port"] == "53"
        assert DEFAULTS["precache_max_queries_per_pass"] == "2000"

    def test_defaults_apply_when_row_absent(self, sync_db_session):
        assert get_setting(sync_db_session, "precache_dns_server") == "dnsdist"
        assert get_setting(sync_db_session, "precache_dns_port") == "53"
        assert get_setting(sync_db_session, "precache_max_queries_per_pass") == "2000"

    def test_stored_row_pins_value_beyond_default_change(self, sync_db_session):
        """Existing deployments with a stored row keep the old value.

        This is the executable statement of the settings-migration concern:
        changing DEFAULTS does NOT update deployments that previously saved
        precache settings (they hold recursor/5300 rows). Alembic revision
        0019_precache_warming_dnsdist flips exactly those rows; see
        tests/integration/test_settings_migration.py.
        """
        set_setting(sync_db_session, "precache_dns_server", "recursor")
        set_setting(sync_db_session, "precache_dns_port", "5300")

        assert get_setting(sync_db_session, "precache_dns_server") == "recursor"
        assert get_setting(sync_db_session, "precache_dns_port") == "5300"
