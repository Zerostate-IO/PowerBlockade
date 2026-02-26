"""Integration tests for node sync API endpoints."""

from datetime import datetime, timezone

from app.models.node import Node


class TestNodeSyncRoutes:
    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {"X-PowerBlockade-Node-Key": api_key}

    def test_register_node_creates_new_node(self, sync_client, sync_db_session):
        node = Node(name="bootstrap", api_key="test_key", status="pending")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = sync_client.post(
            "/api/node-sync/register",
            json={"name": "test_node", "ip_address": "127.0.0.1"},
            headers=self._headers("test_key"),
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_register_node_with_duplicate_name(self, sync_client, sync_db_session):
        existing = Node(name="existing_name", api_key="other_key", status="active")
        sync_db_session.add(existing)
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = sync_client.post(
            "/api/node-sync/register",
            json={"name": "test_node", "ip_address": "127.0.0.1"},
            headers=self._headers("test_key"),
        )
        assert response.status_code == 200

    def test_heartbeat_updates_last_seen(self, sync_client, sync_db_session):
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = sync_client.post(
            "/api/node-sync/heartbeat",
            json={},
            headers=self._headers("test_key"),
        )
        assert response.status_code == 200

    def test_heartbeat_returns_401_for_invalid_key(self, sync_client):
        response = sync_client.post(
            "/api/node-sync/heartbeat",
            json={},
            headers=self._headers("invalid_key"),
        )
        assert response.status_code == 401

    def test_ingest_accepts_events(self, sync_client, sync_db_session):
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        events = [
            {
                "event_id": "uuid-1",
                "ts": datetime.now(timezone.utc).isoformat(),
                "client_ip": "192.168.1.100",
                "qname": "example.com",
                "qtype": 1,
                "blocked": False,
                "latency_ms": 3,
                "node_name": "test_node",
            }
        ]

        response = sync_client.post(
            "/api/node-sync/ingest", json={"events": events}, headers=self._headers("test_key")
        )
        assert response.status_code == 200

    def test_ingest_returns_401_for_invalid_key(self, sync_client):
        events = [{"event_id": "uuid-1", "qname": "example.com"}]

        response = sync_client.post(
            "/api/node-sync/ingest",
            json={"events": events},
            headers=self._headers("invalid_key"),
        )
        assert response.status_code == 401

    def test_get_nodes_lists_nodes(self, authenticated_client, sync_db_session):
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = authenticated_client.get("/nodes")
        assert response.status_code == 200
        assert "test_node" in response.text

    def test_generate_node_creates_node(self, authenticated_client):
        response = authenticated_client.post(
            "/nodes/generate",
            data={"name": "secondary-test", "primary_url": "http://primary.example"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/zip")

    def test_delete_node_works(self, authenticated_client, sync_db_session):
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = authenticated_client.post(
            "/nodes/delete", data={"node_id": node.id}, follow_redirects=False
        )
        assert response.status_code == 302

    def test_get_config_returns_rpz_and_forwardzones(self, sync_client, sync_db_session):
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = sync_client.get(
            "/api/node-sync/config",
            headers=self._headers("test_key"),
        )
        assert response.status_code == 200
        data = response.json()
        assert "rpz_files" in data
        assert "forward_zones" in data
        assert "settings" in data

    def test_get_config_returns_401_for_invalid_key(self, sync_client):
        response = sync_client.get(
            "/api/node-sync/config",
            headers=self._headers("invalid_key"),
        )
        assert response.status_code == 401

    def test_metrics_endpoint_accepts_node_metrics(self, sync_client, sync_db_session):
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        metrics = {
            "node_name": "test_node",
            "cache_hits": 1000,
            "cache_misses": 200,
            "cache_entries": 5000,
            "questions": 1200,
            "concurrent_queries": 5,
            "outgoing_timeouts": 10,
            "servfail_answers": 5,
            "all_outqueries": 500,
            "uptime_seconds": 86400,
            "answers_0_1": 100,
            "answers_1_10": 200,
            "answers_10_100": 300,
            "answers_100_1000": 50,
            "answers_slow": 10,
        }

        response = sync_client.post(
            "/api/node-sync/metrics",
            json=metrics,
            headers=self._headers("test_key"),
        )
        assert response.status_code == 200

    def test_metrics_returns_401_for_invalid_key(self, sync_client):
        response = sync_client.post(
            "/api/node-sync/metrics",
            json={"node_name": "test"},
            headers=self._headers("invalid_key"),
        )
        assert response.status_code == 401

    def test_full_node_registration_flow(self, sync_client, sync_db_session):
        node = Node(name="bootstrap", api_key="sec_key_123", status="pending")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = sync_client.post(
            "/api/node-sync/register",
            json={"name": "secondary-node", "ip_address": "10.0.0.10"},
            headers=self._headers("sec_key_123"),
        )
        assert response.status_code == 200
        node_data = response.json()
        assert node_data["ok"] is True

        response = sync_client.post(
            "/api/node-sync/heartbeat",
            json={},
            headers=self._headers("sec_key_123"),
        )
        assert response.status_code == 200

        response = sync_client.get(
            "/api/node-sync/config",
            headers=self._headers("sec_key_123"),
        )
        assert response.status_code == 200

        events = [
            {
                "event_id": "e2e-test-1",
                "ts": datetime.now(timezone.utc).isoformat(),
                "client_ip": "10.0.0.5",
                "qname": "google.com",
                "qtype": 1,
                "rcode": 0,
                "blocked": False,
                "latency_ms": 25,
                "node_name": "secondary-node",
            }
        ]
        response = sync_client.post(
            "/api/node-sync/ingest",
            json={"events": events},
            headers=self._headers("sec_key_123"),
        )
        assert response.status_code == 200

        metrics = {
            "node_name": "secondary-node",
            "cache_hits": 500,
            "cache_misses": 100,
            "cache_entries": 2500,
            "questions": 600,
            "concurrent_queries": 2,
            "outgoing_timeouts": 3,
            "servfail_answers": 1,
            "all_outqueries": 200,
            "uptime_seconds": 3600,
            "answers_0_1": 50,
            "answers_1_10": 100,
            "answers_10_100": 150,
            "answers_100_1000": 25,
            "answers_slow": 5,
        }
        response = sync_client.post(
            "/api/node-sync/metrics",
            json=metrics,
            headers=self._headers("sec_key_123"),
        )
        assert response.status_code == 200
