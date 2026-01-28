"""Integration tests for forward zones routes."""

from app.models.forward_zone import ForwardZone
from app.models.node import Node


class TestForwardZoneRoutes:
    def test_forward_zones_get_renders_page(self, authenticated_client):
        response = authenticated_client.get("/forwardzones")
        assert response.status_code == 200
        assert "forward" in response.text.lower()

    def test_create_forward_zone_global(self, authenticated_client):
        response = authenticated_client.post(
            "/forwardzones/create",
            data={"name": "test.local", "nameservers": "10.0.1.1"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    def test_create_forward_zone_per_node(self, authenticated_client, sync_db_session):
        node = Node(name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        response = authenticated_client.post(
            "/forwardzones/create",
            data={"name": "test.local", "nameservers": "10.0.1.1", "node_id": node.id},
            follow_redirects=False,
        )
        assert response.status_code == 303

    def test_edit_forward_zone(self, authenticated_client, sync_db_session):
        zone = ForwardZone(name="test.local", nameservers="10.0.1.1", scope="global")
        sync_db_session.add(zone)
        sync_db_session.commit()

        response = authenticated_client.post(
            f"/forwardzones/{zone.id}/edit",
            data={"name": "new.local", "nameservers": "10.0.1.2"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    def test_delete_forward_zone(self, authenticated_client, sync_db_session):
        zone = ForwardZone(name="test.local", nameservers="10.0.1.1", scope="global")
        sync_db_session.add(zone)
        sync_db_session.commit()

        response = authenticated_client.post(
            f"/forwardzones/{zone.id}/delete", follow_redirects=False
        )
        assert response.status_code == 303

    def test_apply_forward_zones(self, authenticated_client, sync_db_session):
        zone = ForwardZone(name="test.local", nameservers="10.0.1.1", scope="global")
        sync_db_session.add(zone)
        sync_db_session.commit()

        response = authenticated_client.post("/forwardzones/apply", follow_redirects=False)
        assert response.status_code == 303
