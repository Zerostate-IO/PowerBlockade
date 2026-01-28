"""Integration tests for node sync API endpoints."""

import pytest
from datetime import datetime, timezone

from app.models.node import Node


class TestNodeSyncRoutes:
    def test_register_node_creates_new_node(self, sync_client):
        response = sync_client.post(
            "/api/node-sync/register",
            json={"name": "test_node", "api_key": "test_key"},
        )
        assert response.status_code == 201
        assert response.json()["name"] == "test_node"

    def test_register_node_with_duplicate_name(self, sync_client, sync_db_session):
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = sync_client.post(
            "/api/node-sync/register",
            json={"name": "test_node", "api_key": "different_key"},
        )
        assert response.status_code == 400

    def test_heartbeat_updates_last_seen(self, sync_client, sync_db_session):
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = sync_client.post(
            "/api/node-sync/heartbeat",
            headers={"X-PowerBlockade-Node-Key": "test_key"},
        )
        assert response.status_code == 200

    def test_heartbeat_returns_401_for_invalid_key(self, sync_client):
        response = sync_client.post(
            "/api/node-sync/heartbeat",
            headers={"X-PowerBlockade-Node-Key": "invalid_key"},
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
            "/api/node-sync/ingest",
            json=events,
            headers={"X-PowerBlockade-Node-Key": "test_key"},
        )
        assert response.status_code == 201

    def test_ingest_returns_401_for_invalid_key(self, sync_client):
        events = [{"event_id": "uuid-1", "qname": "example.com"}]

        response = sync_client.post(
            "/api/node-sync/ingest",
            json=events,
            headers={"X-PowerBlockade-Node-Key": "invalid_key"},
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
            follow_redirects=False,
        )
        assert response.status_code in [200, 303]

    def test_delete_node_works(self, authenticated_client, sync_db_session):
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = authenticated_client.post(
            f"/nodes/{node.id}/delete", follow_redirects=False
        )
        assert response.status_code == 303
