"""Integration tests for blocklist routes."""

from app.models.blocklist import Blocklist


class TestBlocklistRoutes:
    def test_blocklist_get_renders_page(self, authenticated_client):
        response = authenticated_client.get("/blocklists")
        assert response.status_code == 200
        assert "blocklist" in response.text.lower()

    def test_create_blocklist(self, authenticated_client):
        response = authenticated_client.post(
            "/blocklists/create",
            data={
                "url": "https://example.com/list.txt",
                "name": "Test List",
                "list_type": "block",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    def test_edit_blocklist(self, authenticated_client, sync_db_session):
        blocklist = Blocklist(
            url="https://example.com/list.txt",
            name="Test List",
            list_type="block",
            enabled=True,
        )
        sync_db_session.add(blocklist)
        sync_db_session.commit()

        response = authenticated_client.post(
            f"/blocklists/{blocklist.id}/edit",
            data={
                "url": "https://example.com/new.txt",
                "name": "Updated Name",
                "list_type": "block",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    def test_delete_blocklist(self, authenticated_client, sync_db_session):
        blocklist = Blocklist(
            url="https://example.com/list.txt",
            name="Test List",
            list_type="block",
            enabled=True,
        )
        sync_db_session.add(blocklist)
        sync_db_session.commit()

        response = authenticated_client.post(
            f"/blocklists/{blocklist.id}/delete", follow_redirects=False
        )
        assert response.status_code == 303

    def test_blocklist_apply_endpoint(self, authenticated_client, sync_db_session):
        blocklist = Blocklist(
            url="https://example.com/list.txt",
            name="Test List",
            list_type="block",
            enabled=True,
        )
        sync_db_session.add(blocklist)
        sync_db_session.commit()

        response = authenticated_client.post("/blocklists/apply", follow_redirects=False)
        assert response.status_code == 303
