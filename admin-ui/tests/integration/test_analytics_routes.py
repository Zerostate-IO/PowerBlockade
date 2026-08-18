"""Integration tests for analytics routes."""

import inspect
from datetime import datetime, timedelta, timezone

from app.models.query_rollup import QueryRollup
from app.routers.analytics import index_page
from app.services.rollups import reset_stats_cache


class TestAnalyticsRoutes:
    def test_dashboard_renders(self, authenticated_client):
        reset_stats_cache()
        response = authenticated_client.get("/")
        assert response.status_code == 200
        assert "dashboard" in response.text.lower()

    def test_dashboard_shows_stats_from_rollups(self, authenticated_client, sync_db_session):
        """Dashboard should use rollup-backed stats, not raw 24h DNSQueryEvent scans."""
        reset_stats_cache()

        # Seed a recent hourly rollup within the 24h window
        hour_start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        rollup = QueryRollup(
            bucket_start=hour_start,
            granularity="hourly",
            client_id=None,
            node_id=None,
            total_queries=200,
            blocked_queries=50,
            nxdomain_count=5,
            servfail_count=2,
            cache_hits=80,
            avg_latency_ms=12,
            unique_domains=60,
        )
        sync_db_session.add(rollup)
        sync_db_session.commit()

        reset_stats_cache()
        response = authenticated_client.get("/")
        assert response.status_code == 200
        assert "dashboard" in response.text.lower()

    def test_dashboard_no_raw_24h_aggregate_in_index_page(self):
        """Static assertion: index_page source must not contain raw 24h DNSQueryEvent scans."""
        source = inspect.getsource(index_page)
        # The function should not reference DNSQueryEvent directly
        assert "DNSQueryEvent" not in source
        # No raw count/avg aggregate patterns over a 24h window
        assert "sa.func.count(DNSQueryEvent" not in source
        assert "sa.func.avg(DNSQueryEvent" not in source

    def test_dashboard_source_uses_get_dashboard_stats(self):
        """Static assertion: index_page must call get_dashboard_stats."""
        source = inspect.getsource(index_page)
        assert "get_dashboard_stats" in source

    def test_logs_page_renders(self, authenticated_client):
        response = authenticated_client.get("/logs")
        assert response.status_code == 200

    def test_clients_page_renders(self, authenticated_client):
        response = authenticated_client.get("/clients")
        assert response.status_code == 200

    def test_domains_page_renders(self, authenticated_client):
        response = authenticated_client.get("/domains")
        assert response.status_code == 200

    def test_blocked_page_renders(self, authenticated_client):
        response = authenticated_client.get("/blocked")
        assert response.status_code == 200

    def test_failures_page_renders(self, authenticated_client):
        response = authenticated_client.get("/failures")
        assert response.status_code == 200

    def test_precache_page_renders(self, authenticated_client):
        response = authenticated_client.get("/precache")
        assert response.status_code == 200

    def test_metrics_endpoint_returns_prometheus_format(self, authenticated_client):
        response = authenticated_client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")

    def test_metrics_endpoint_contains_expected_metrics(self, authenticated_client):
        response = authenticated_client.get("/metrics")
        text = response.text
        assert "powerblockade_queries_total" in text
        assert "powerblockade_blocked_total" in text
        assert "powerblockade_cache_hits_total" in text
        assert "powerblockade_block_rate" in text
        assert "powerblockade_cache_hit_rate" in text
        assert "powerblockade_time_saved_seconds" in text
        assert "powerblockade_qps" in text
        assert "powerblockade_stats_cache_age_seconds" in text
        assert "powerblockade_rollup_lag_seconds" in text
        assert "powerblockade_stats_edge_delta_total" in text

    def test_metrics_endpoint_no_raw_dns_query_event_import(self):
        import pathlib

        metrics_path = pathlib.Path(__file__).resolve().parent.parent.parent / "app" / "routers" / "metrics.py"
        source = metrics_path.read_text()
        assert "DNSQueryEvent" not in source


class TestInternalTrafficFiltering:
    """is_internal events are excluded from analytics by default (issue #48)."""

    @staticmethod
    def _seed_events(sync_db_session) -> None:
        from app.models.client import Client
        from app.models.dns_query_event import DNSQueryEvent

        external_client = Client(ip="10.5.5.50")
        internal_client = Client(ip="172.30.0.3")
        sync_db_session.add_all([external_client, internal_client])
        sync_db_session.flush()

        now = datetime.now(timezone.utc)
        sync_db_session.add_all(
            [
                DNSQueryEvent(
                    event_id="internal-1",
                    ts=now,
                    client_ip="172.30.0.3",
                    client_id=internal_client.id,
                    qname="internal.example.com",
                    qtype=1,
                    rcode=0,
                    blocked=False,
                    is_internal=True,
                ),
                DNSQueryEvent(
                    event_id="external-1",
                    ts=now,
                    client_ip="10.5.5.50",
                    client_id=external_client.id,
                    qname="external.example.com",
                    qtype=1,
                    rcode=0,
                    blocked=False,
                    is_internal=False,
                ),
            ]
        )
        sync_db_session.commit()

    def test_logs_exclude_internal_by_default(self, authenticated_client, sync_db_session):
        self._seed_events(sync_db_session)
        response = authenticated_client.get("/logs?view=all&window=24h")
        assert response.status_code == 200
        assert "external.example.com" in response.text
        assert "internal.example.com" not in response.text

    def test_logs_include_internal_with_param(self, authenticated_client, sync_db_session):
        self._seed_events(sync_db_session)
        response = authenticated_client.get("/logs?view=all&window=24h&include_internal=1")
        assert response.status_code == 200
        assert "internal.example.com" in response.text

    def test_domains_exclude_internal_by_default(self, authenticated_client, sync_db_session):
        self._seed_events(sync_db_session)
        response = authenticated_client.get("/domains")
        assert response.status_code == 200
        assert "external.example.com" in response.text
        assert "internal.example.com" not in response.text

    def test_history_excludes_internal_by_default(self, authenticated_client, sync_db_session):
        from app.services.rollups import reset_stats_cache

        reset_stats_cache()
        self._seed_events(sync_db_session)
        response = authenticated_client.get("/api/analytics/history?window=24h")
        assert response.status_code == 200
        data = response.json()
        # Internal event excluded: only the external event is counted.
        assert sum(data["series"]["total"]) == 1

    def test_history_includes_internal_with_param(self, authenticated_client, sync_db_session):
        from app.services.rollups import reset_stats_cache

        reset_stats_cache()
        self._seed_events(sync_db_session)
        response = authenticated_client.get("/api/analytics/history?window=24h&include_internal=1")
        assert response.status_code == 200
        data = response.json()
        assert sum(data["series"]["total"]) == 2
