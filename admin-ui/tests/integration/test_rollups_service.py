"""Integration tests for rollups service.

These tests require PostgreSQL because compute_hourly_rollup and compute_daily_rollup
create QueryRollup records without explicit IDs, relying on auto-increment (SERIAL).
SQLite doesn't auto-increment BigInteger primary keys.
"""

from datetime import datetime, timedelta, timezone
from time import sleep

import pytest

from app.models.client import Client
from app.models.dns_query_event import DNSQueryEvent
from app.models.node import Node
from app.models.query_rollup import QueryRollup
from app.services.rollups import (
    backfill_hourly_rollups,
    compute_daily_rollup,
    compute_hourly_rollup,
    get_dashboard_stats,
    reset_stats_cache,
    run_rollup_job,
)


@pytest.mark.integration
class TestComputeHourlyRollup:
    def test_aggregates_events_by_client_and_node(self, pg_session):
        node = Node(id=1, name="test_node", api_key="test_key", status="active")
        client = Client(id=1, ip="192.168.1.100")
        pg_session.add_all([node, client])
        pg_session.commit()

        hour_start = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        for i in range(5):
            event = DNSQueryEvent(
                id=i + 1,
                ts=hour_start + timedelta(minutes=i * 10),
                client_ip="192.168.1.100",
                client_id=client.id,
                node_id=node.id,
                qname=f"test{i}.example.com",
                qtype=1,
                rcode=0,
                blocked=(i % 2 == 0),
                latency_ms=i + 1,
            )
            pg_session.add(event)
        pg_session.commit()

        count = compute_hourly_rollup(pg_session, hour_start)

        assert count == 1
        rollup = pg_session.query(QueryRollup).first()
        assert rollup is not None
        assert rollup.total_queries == 5
        assert rollup.blocked_queries == 3
        assert rollup.client_id == client.id
        assert rollup.node_id == node.id
        assert rollup.granularity == "hourly"

    def test_counts_cache_hits_based_on_latency(self, pg_session):
        hour_start = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        for i in range(10):
            latency = 2 if i < 6 else 20
            event = DNSQueryEvent(
                id=i + 1,
                ts=hour_start + timedelta(minutes=i * 5),
                client_ip="192.168.1.100",
                qname=f"test{i}.example.com",
                qtype=1,
                rcode=0,
                blocked=False,
                latency_ms=latency,
            )
            pg_session.add(event)
        pg_session.commit()

        compute_hourly_rollup(pg_session, hour_start)

        rollup = pg_session.query(QueryRollup).first()
        assert rollup is not None
        assert rollup.cache_hits == 6
        assert rollup.total_queries == 10

    def test_counts_nxdomain_and_servfail(self, pg_session):
        hour_start = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        rcodes = [0, 0, 3, 3, 3, 2, 2, 0, 0, 0]
        for i, rcode in enumerate(rcodes):
            event = DNSQueryEvent(
                id=i + 1,
                ts=hour_start + timedelta(minutes=i * 5),
                client_ip="192.168.1.100",
                qname=f"test{i}.example.com",
                qtype=1,
                rcode=rcode,
                blocked=False,
            )
            pg_session.add(event)
        pg_session.commit()

        compute_hourly_rollup(pg_session, hour_start)

        rollup = pg_session.query(QueryRollup).first()
        assert rollup.nxdomain_count == 3
        assert rollup.servfail_count == 2

    def test_calculates_average_latency(self, pg_session):
        hour_start = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        for i, latency in enumerate([10, 20, 30, 40]):
            event = DNSQueryEvent(
                id=i + 1,
                ts=hour_start + timedelta(minutes=i * 10),
                client_ip="192.168.1.100",
                qname=f"test{i}.example.com",
                qtype=1,
                rcode=0,
                blocked=False,
                latency_ms=latency,
            )
            pg_session.add(event)
        pg_session.commit()

        compute_hourly_rollup(pg_session, hour_start)

        rollup = pg_session.query(QueryRollup).first()
        assert rollup.avg_latency_ms == 25

    def test_counts_unique_domains(self, pg_session):
        hour_start = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        domains = ["a.com", "b.com", "a.com", "c.com", "a.com", "b.com"]
        for i, domain in enumerate(domains):
            event = DNSQueryEvent(
                id=i + 1,
                ts=hour_start + timedelta(minutes=i * 5),
                client_ip="192.168.1.100",
                qname=domain,
                qtype=1,
                rcode=0,
                blocked=False,
            )
            pg_session.add(event)
        pg_session.commit()

        compute_hourly_rollup(pg_session, hour_start)

        rollup = pg_session.query(QueryRollup).first()
        assert rollup.unique_domains == 3

    def test_returns_zero_for_no_events(self, pg_session):
        hour_start = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        count = compute_hourly_rollup(pg_session, hour_start)
        assert count == 0

    def test_ignores_events_outside_hour(self, pg_session):
        hour_start = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        prev_hour_event = DNSQueryEvent(
            id=1,
            ts=hour_start - timedelta(minutes=30),
            client_ip="192.168.1.100",
            qname="prev.example.com",
            qtype=1,
            rcode=0,
            blocked=False,
        )
        current_event = DNSQueryEvent(
            id=2,
            ts=hour_start + timedelta(minutes=30),
            client_ip="192.168.1.100",
            qname="current.example.com",
            qtype=1,
            rcode=0,
            blocked=False,
        )
        next_hour_event = DNSQueryEvent(
            id=3,
            ts=hour_start + timedelta(minutes=90),
            client_ip="192.168.1.100",
            qname="next.example.com",
            qtype=1,
            rcode=0,
            blocked=False,
        )
        pg_session.add_all([prev_hour_event, current_event, next_hour_event])
        pg_session.commit()

        compute_hourly_rollup(pg_session, hour_start)

        rollup = pg_session.query(QueryRollup).first()
        assert rollup.total_queries == 1


@pytest.mark.integration
class TestComputeDailyRollup:
    def test_aggregates_hourly_rollups(self, pg_session):
        day_start = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)

        for hour in range(24):
            rollup = QueryRollup(
                bucket_start=day_start + timedelta(hours=hour),
                granularity="hourly",
                total_queries=100,
                blocked_queries=10,
                nxdomain_count=5,
                servfail_count=2,
                cache_hits=50,
                avg_latency_ms=20,
                unique_domains=30,
            )
            pg_session.add(rollup)
        pg_session.commit()

        count = compute_daily_rollup(pg_session, day_start)

        assert count == 1
        daily = pg_session.query(QueryRollup).filter(QueryRollup.granularity == "daily").first()
        assert daily is not None
        assert daily.total_queries == 2400
        assert daily.blocked_queries == 240
        assert daily.nxdomain_count == 120
        assert daily.servfail_count == 48
        assert daily.cache_hits == 1200


@pytest.mark.integration
class TestGetDashboardStats:
    def setup_method(self):
        reset_stats_cache()

    def test_uses_completed_rollups_for_full_hours(self, sync_db_session):
        now = datetime.now(timezone.utc)
        h2 = (now - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
        h1 = (now - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

        pg_session = sync_db_session
        for bucket in [h2, h1]:
            rollup = QueryRollup(
                bucket_start=bucket,
                granularity="hourly",
                total_queries=200,
                blocked_queries=20,
                nxdomain_count=10,
                servfail_count=5,
                cache_hits=100,
                avg_latency_ms=30,
                unique_domains=15,
            )
            pg_session.add(rollup)
        pg_session.commit()

        stats = get_dashboard_stats(pg_session, hours=6)

        assert stats["total_queries"] >= 400
        assert stats["blocked_queries"] >= 40
        assert stats["blocked_pct"] > 0
        assert stats["cache_hit_pct"] > 0
        assert "time_saved_ms" in stats
        assert "qps" in stats
        assert "block_rate" in stats
        assert "cache_hit_rate" in stats
        assert "unique_domains" in stats
        assert "avg_latency_ms" in stats

    def test_includes_start_partial_edge_events(self, sync_db_session):
        now = datetime.now(timezone.utc)
        three_hours_ago = now - timedelta(hours=3)
        start_hour = three_hours_ago.replace(minute=0, second=0, microsecond=0)
        full_start = start_hour + timedelta(hours=1)

        pg_session = sync_db_session

        rollup = QueryRollup(
            bucket_start=full_start,
            granularity="hourly",
            total_queries=100,
            blocked_queries=10,
            nxdomain_count=5,
            servfail_count=2,
            cache_hits=50,
            avg_latency_ms=20,
            unique_domains=8,
        )
        pg_session.add(rollup)
        pg_session.commit()

        edge_event = DNSQueryEvent(
            id=9001,
            ts=three_hours_ago + timedelta(seconds=30),
            client_ip="192.168.1.50",
            qname="edge.example.com",
            qtype=1,
            rcode=0,
            blocked=True,
            latency_ms=10,
        )
        pg_session.add(edge_event)
        pg_session.commit()

        reset_stats_cache()
        stats = get_dashboard_stats(pg_session, hours=3)

        assert stats["total_queries"] >= 101
        assert stats["blocked_queries"] >= 11

    def test_includes_current_partial_edge_events(self, sync_db_session):
        now = datetime.now(timezone.utc)
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        prev_hour = current_hour - timedelta(hours=1)

        pg_session = sync_db_session

        rollup = QueryRollup(
            bucket_start=prev_hour,
            granularity="hourly",
            total_queries=50,
            blocked_queries=5,
            nxdomain_count=2,
            servfail_count=1,
            cache_hits=25,
            avg_latency_ms=15,
            unique_domains=10,
        )
        pg_session.add(rollup)
        pg_session.commit()

        recent_event = DNSQueryEvent(
            id=9002,
            ts=now - timedelta(minutes=5),
            client_ip="192.168.1.60",
            qname="recent.example.com",
            qtype=1,
            rcode=0,
            blocked=False,
            latency_ms=8,
        )
        pg_session.add(recent_event)
        pg_session.commit()

        reset_stats_cache()
        stats = get_dashboard_stats(pg_session, hours=3)

        assert stats["total_queries"] >= 51

    def test_returns_zeros_for_no_data(self, sync_db_session):
        reset_stats_cache()
        stats = get_dashboard_stats(sync_db_session, hours=24)

        assert stats["total_queries"] == 0
        assert stats["blocked_queries"] == 0
        assert stats["blocked_pct"] == 0.0
        assert stats["cache_hit_pct"] == 0.0
        assert stats["avg_latency_ms"] == 0
        assert stats["time_saved_ms"] == 0
        assert stats["qps"] == 0.0
        assert stats["cache_age_seconds"] == 0.0
        assert stats["edge_delta_total"] == 0

    def test_cache_suppresses_repeated_queries(self, sync_db_session):
        now = datetime.now(timezone.utc)
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        prev_hour = current_hour - timedelta(hours=1)

        pg_session = sync_db_session
        rollup = QueryRollup(
            bucket_start=prev_hour,
            granularity="hourly",
            total_queries=100,
            blocked_queries=10,
            nxdomain_count=5,
            servfail_count=2,
            cache_hits=50,
            avg_latency_ms=20,
            unique_domains=7,
        )
        pg_session.add(rollup)
        pg_session.commit()

        reset_stats_cache()
        stats1 = get_dashboard_stats(pg_session, hours=6)

        new_event = DNSQueryEvent(
            id=9003,
            ts=now - timedelta(minutes=1),
            client_ip="192.168.1.70",
            qname="cached.example.com",
            qtype=1,
            rcode=0,
            blocked=False,
            latency_ms=5,
        )
        pg_session.add(new_event)
        pg_session.commit()

        sleep(0.15)
        stats2 = get_dashboard_stats(pg_session, hours=6)

        assert stats2["total_queries"] == stats1["total_queries"]
        assert stats2["cache_age_seconds"] > 0

    def test_short_window_uses_raw_query(self, sync_db_session):
        now = datetime.now(timezone.utc)
        pg_session = sync_db_session

        for i in range(3):
            event = DNSQueryEvent(
                id=8000 + i,
                ts=now - timedelta(minutes=30 - i * 10),
                client_ip="192.168.1.80",
                qname=f"short{i}.example.com",
                qtype=1,
                rcode=0,
                blocked=(i == 0),
                latency_ms=10 + i * 5,
            )
            pg_session.add(event)
        pg_session.commit()

        reset_stats_cache()
        stats = get_dashboard_stats(pg_session, hours=1)

        assert stats["total_queries"] >= 3
        assert stats["blocked_queries"] >= 1
        assert stats["cache_age_seconds"] == 0.0
        assert stats["edge_delta_total"] >= 3

    def test_weighted_average_latency(self, sync_db_session):
        now = datetime.now(timezone.utc)
        h2 = (now - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)

        pg_session = sync_db_session

        r1 = QueryRollup(
            bucket_start=h2,
            granularity="hourly",
            total_queries=100,
            blocked_queries=0,
            nxdomain_count=0,
            servfail_count=0,
            cache_hits=0,
            avg_latency_ms=10,
            unique_domains=5,
        )
        r2 = QueryRollup(
            bucket_start=h2 + timedelta(hours=1),
            granularity="hourly",
            total_queries=200,
            blocked_queries=0,
            nxdomain_count=0,
            servfail_count=0,
            cache_hits=0,
            avg_latency_ms=40,
            unique_domains=8,
        )
        pg_session.add_all([r1, r2])
        pg_session.commit()

        reset_stats_cache()
        stats = get_dashboard_stats(pg_session, hours=6)

        expected_avg = int((100 * 10 + 200 * 40) / 300)
        assert stats["avg_latency_ms"] == expected_avg

    def test_new_return_keys_present(self, sync_db_session):
        reset_stats_cache()
        stats = get_dashboard_stats(sync_db_session, hours=24)

        for key in [
            "total_queries",
            "blocked_queries",
            "nxdomain_count",
            "servfail_count",
            "cache_hits",
            "avg_latency_ms",
            "blocked_pct",
            "cache_hit_pct",
            "unique_domains",
            "time_saved_ms",
            "qps",
            "block_rate",
            "cache_hit_rate",
            "cache_age_seconds",
            "rollup_lag_seconds",
            "edge_delta_total",
        ]:
            assert key in stats, f"missing key: {key}"

    def test_filters_by_time_window(self, sync_db_session):
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)

        recent = QueryRollup(
            bucket_start=hour_start - timedelta(hours=2),
            granularity="hourly",
            total_queries=100,
        )
        old = QueryRollup(
            bucket_start=hour_start - timedelta(hours=48),
            granularity="hourly",
            total_queries=5000,
        )
        sync_db_session.add_all([recent, old])
        sync_db_session.commit()

        reset_stats_cache()
        stats = get_dashboard_stats(sync_db_session, hours=24)

        assert stats["total_queries"] == 100


class TestRunRollupJob:
    def test_returns_rollup_counts(self, sync_db_session):
        result = run_rollup_job(sync_db_session)

        assert isinstance(result, dict)
        assert "hourly" in result
        assert "daily" in result
        assert isinstance(result["hourly"], int)
        assert isinstance(result["daily"], int)


@pytest.mark.integration
class TestBackfillHourlyRollups:
    def test_backfill_is_idempotent(self, pg_session):
        now = datetime.now(timezone.utc)
        hour_start = (now - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

        for i in range(5):
            event = DNSQueryEvent(
                id=5000 + i,
                ts=hour_start + timedelta(minutes=i * 10),
                client_ip="192.168.1.100",
                qname=f"bf{i}.example.com",
                qtype=1,
                rcode=0,
                blocked=(i % 2 == 0),
                latency_ms=10,
            )
            pg_session.add(event)
        pg_session.commit()

        count1 = backfill_hourly_rollups(pg_session, hours=3)
        count2 = backfill_hourly_rollups(pg_session, hours=3)

        assert count1 == count2

        rollups = pg_session.query(QueryRollup).filter(
            QueryRollup.granularity == "hourly"
        ).all()
        by_bucket = {}
        for r in rollups:
            key = r.bucket_start.isoformat()
            if key in by_bucket:
                assert False, f"Duplicate rollup for bucket {key}"
            by_bucket[key] = r

    def test_backfill_clamps_hours(self, pg_session):
        count = backfill_hourly_rollups(pg_session, hours=9999)
        assert isinstance(count, int)

        count2 = backfill_hourly_rollups(pg_session, hours=0)
        assert isinstance(count2, int)

        count3 = backfill_hourly_rollups(pg_session, hours=-5)
        assert isinstance(count3, int)
