"""Integration tests for rollups service.

These tests require PostgreSQL because compute_hourly_rollup and compute_daily_rollup
create QueryRollup records without explicit IDs, relying on auto-increment (SERIAL).
SQLite doesn't auto-increment BigInteger primary keys.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.client import Client
from app.models.dns_query_event import DNSQueryEvent
from app.models.node import Node
from app.models.query_rollup import QueryRollup
from app.services.rollups import (
    compute_daily_rollup,
    compute_hourly_rollup,
    get_dashboard_stats,
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
                id=hour + 1,
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


class TestGetDashboardStats:
    def test_returns_aggregated_stats(self, sync_db_session):
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)

        rollup = QueryRollup(
            id=1,
            bucket_start=hour_start,
            granularity="hourly",
            total_queries=1000,
            blocked_queries=100,
            nxdomain_count=50,
            servfail_count=10,
            cache_hits=600,
            avg_latency_ms=15,
        )
        sync_db_session.add(rollup)
        sync_db_session.commit()

        stats = get_dashboard_stats(sync_db_session, hours=24)

        assert stats["total_queries"] == 1000
        assert stats["blocked_queries"] == 100
        assert stats["nxdomain_count"] == 50
        assert stats["servfail_count"] == 10
        assert stats["cache_hits"] == 600
        assert stats["blocked_pct"] == 10.0
        assert stats["cache_hit_pct"] == 60.0

    def test_returns_zeros_for_no_data(self, sync_db_session):
        stats = get_dashboard_stats(sync_db_session, hours=24)

        assert stats["total_queries"] == 0
        assert stats["blocked_queries"] == 0
        assert stats["blocked_pct"] == 0.0
        assert stats["cache_hit_pct"] == 0.0

    def test_filters_by_time_window(self, sync_db_session):
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)

        recent = QueryRollup(
            id=1,
            bucket_start=hour_start - timedelta(hours=2),
            granularity="hourly",
            total_queries=100,
        )
        old = QueryRollup(
            id=2,
            bucket_start=hour_start - timedelta(hours=48),
            granularity="hourly",
            total_queries=5000,
        )
        sync_db_session.add_all([recent, old])
        sync_db_session.commit()

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
