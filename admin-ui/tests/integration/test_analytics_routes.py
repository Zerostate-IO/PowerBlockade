"""Integration tests for analytics routes."""

from datetime import datetime, timezone

from app.models.dns_query_event import DNSQueryEvent


class TestAnalyticsRoutes:
    def test_dashboard_renders(self, authenticated_client):
        response = authenticated_client.get("/")
        assert response.status_code == 200
        assert "dashboard" in response.text.lower()

    def test_dashboard_shows_stats_from_events(self, authenticated_client, sync_db_session):
        for i in range(10):
            event = DNSQueryEvent(
                ts=datetime.now(timezone.utc),
                client_ip="192.168.1.100",
                qname=f"example{i}.com",
                qtype=1,
                blocked=i % 2 == 0,
                latency_ms=3 + i,
            )
            sync_db_session.add(event)
        sync_db_session.commit()

        response = authenticated_client.get("/")
        assert response.status_code == 200
        assert "dashboard" in response.text.lower()

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
