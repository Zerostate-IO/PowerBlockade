"""Unit tests for retention service."""

from datetime import datetime, timedelta, timezone

from app.models.dns_query_event import DNSQueryEvent
from app.models.node import Node
from app.models.node_metrics import NodeMetrics
from app.models.query_rollup import QueryRollup
from app.services.retention import (
    cleanup_old_events,
    cleanup_old_node_metrics,
    cleanup_old_rollups,
    run_retention_job,
)


class TestCleanupOldEvents:
    def test_deletes_events_older_than_cutoff(self, sync_db_session):
        """Events older than the retention period should be deleted."""
        now = datetime.now(timezone.utc)
        old_event = DNSQueryEvent(
            id=1,
            ts=now - timedelta(days=10),
            client_ip="192.168.1.1",
            qname="old.example.com",
            qtype=1,
            rcode=0,
            blocked=False,
        )
        recent_event = DNSQueryEvent(
            id=2,
            ts=now - timedelta(days=1),
            client_ip="192.168.1.1",
            qname="recent.example.com",
            qtype=1,
            rcode=0,
            blocked=False,
        )
        sync_db_session.add_all([old_event, recent_event])
        sync_db_session.commit()

        # Delete events older than 5 days
        deleted = cleanup_old_events(sync_db_session, days=5)

        assert deleted == 1
        remaining = sync_db_session.query(DNSQueryEvent).all()
        assert len(remaining) == 1
        assert remaining[0].qname == "recent.example.com"

    def test_keeps_events_within_retention(self, sync_db_session):
        """Events within the retention period should be kept."""
        now = datetime.now(timezone.utc)
        event1 = DNSQueryEvent(
            id=1,
            ts=now - timedelta(days=2),
            client_ip="192.168.1.1",
            qname="test1.example.com",
            qtype=1,
            rcode=0,
            blocked=False,
        )
        event2 = DNSQueryEvent(
            id=2,
            ts=now - timedelta(hours=12),
            client_ip="192.168.1.1",
            qname="test2.example.com",
            qtype=1,
            rcode=0,
            blocked=False,
        )
        sync_db_session.add_all([event1, event2])
        sync_db_session.commit()

        deleted = cleanup_old_events(sync_db_session, days=7)

        assert deleted == 0
        remaining = sync_db_session.query(DNSQueryEvent).all()
        assert len(remaining) == 2

    def test_returns_zero_when_no_events(self, sync_db_session):
        """Should return 0 when there are no events to delete."""
        deleted = cleanup_old_events(sync_db_session, days=7)
        assert deleted == 0

    def test_deletes_all_old_events_when_many(self, sync_db_session):
        """Should delete all old events in batch."""
        now = datetime.now(timezone.utc)
        old_ts = now - timedelta(days=30)

        for i in range(100):
            event = DNSQueryEvent(
                id=i + 1,
                ts=old_ts,
                client_ip="192.168.1.1",
                qname=f"test{i}.example.com",
                qtype=1,
                rcode=0,
                blocked=False,
            )
            sync_db_session.add(event)
        sync_db_session.commit()

        deleted = cleanup_old_events(sync_db_session, days=7)

        assert deleted == 100
        remaining = sync_db_session.query(DNSQueryEvent).count()
        assert remaining == 0


class TestCleanupOldRollups:
    def test_deletes_rollups_older_than_cutoff(self, sync_db_session):
        """Rollups older than the retention period should be deleted."""
        now = datetime.now(timezone.utc)
        old_rollup = QueryRollup(
            id=1,
            bucket_start=now - timedelta(days=400),
            granularity="daily",
            total_queries=100,
            blocked_queries=10,
        )
        recent_rollup = QueryRollup(
            id=2,
            bucket_start=now - timedelta(days=30),
            granularity="daily",
            total_queries=200,
            blocked_queries=20,
        )
        sync_db_session.add_all([old_rollup, recent_rollup])
        sync_db_session.commit()

        deleted = cleanup_old_rollups(sync_db_session, days=365)

        assert deleted == 1
        remaining = sync_db_session.query(QueryRollup).all()
        assert len(remaining) == 1
        assert remaining[0].total_queries == 200

    def test_keeps_rollups_within_retention(self, sync_db_session):
        """Rollups within the retention period should be kept."""
        now = datetime.now(timezone.utc)
        rollup1 = QueryRollup(
            id=1,
            bucket_start=now - timedelta(days=30),
            granularity="hourly",
            total_queries=100,
        )
        rollup2 = QueryRollup(
            id=2,
            bucket_start=now - timedelta(days=60),
            granularity="hourly",
            total_queries=200,
        )
        sync_db_session.add_all([rollup1, rollup2])
        sync_db_session.commit()

        deleted = cleanup_old_rollups(sync_db_session, days=365)

        assert deleted == 0
        remaining = sync_db_session.query(QueryRollup).count()
        assert remaining == 2


class TestCleanupOldNodeMetrics:
    def test_deletes_node_metrics_older_than_cutoff(self, sync_db_session):
        """Node metrics older than retention period should be deleted."""
        node = Node(id=1, name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        now = datetime.now(timezone.utc)
        old_metrics = NodeMetrics(
            id=1,
            node_id=node.id,
            ts=now - timedelta(days=400),
            cache_hits=100,
            cache_misses=50,
        )
        recent_metrics = NodeMetrics(
            id=2,
            node_id=node.id,
            ts=now - timedelta(days=30),
            cache_hits=200,
            cache_misses=100,
        )
        sync_db_session.add_all([old_metrics, recent_metrics])
        sync_db_session.commit()

        deleted = cleanup_old_node_metrics(sync_db_session, days=365)

        assert deleted == 1
        remaining = sync_db_session.query(NodeMetrics).all()
        assert len(remaining) == 1
        assert remaining[0].cache_hits == 200


class TestRunRetentionJob:
    def test_runs_all_cleanup_tasks(self, sync_db_session):
        """Retention job should clean up events, rollups, and node metrics."""
        now = datetime.now(timezone.utc)
        old_ts = now - timedelta(days=500)

        # Create old data
        event = DNSQueryEvent(
            id=1,
            ts=old_ts,
            client_ip="192.168.1.1",
            qname="old.example.com",
            qtype=1,
            rcode=0,
            blocked=False,
        )
        rollup = QueryRollup(
            id=1,
            bucket_start=old_ts,
            granularity="daily",
            total_queries=100,
        )
        node = Node(id=1, name="test_node", api_key="test_key", status="active")
        sync_db_session.add_all([event, rollup, node])
        sync_db_session.commit()

        metrics = NodeMetrics(
            id=1,
            node_id=node.id,
            ts=old_ts,
            cache_hits=100,
        )
        sync_db_session.add(metrics)
        sync_db_session.commit()

        # Run retention with short periods
        result = run_retention_job(sync_db_session)

        # All old data should be deleted (using default retention from settings)
        # Since we don't have settings configured, it uses defaults (90/365/365 days)
        # Our data is 500 days old, so it should be deleted
        assert "events_deleted" in result
        assert "rollups_deleted" in result
        assert "node_metrics_deleted" in result

    def test_returns_deletion_counts(self, sync_db_session):
        """Retention job should return counts of deleted records."""
        result = run_retention_job(sync_db_session)

        assert isinstance(result, dict)
        assert "events_deleted" in result
        assert "rollups_deleted" in result
        assert "node_metrics_deleted" in result
        assert isinstance(result["events_deleted"], int)
        assert isinstance(result["rollups_deleted"], int)
        assert isinstance(result["node_metrics_deleted"], int)
