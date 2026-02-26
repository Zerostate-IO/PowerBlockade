"""Integration tests for auth routes."""


class TestAuthRoutes:
    @staticmethod
    def _csrf_token(client):
        response = client.get("/login")
        assert response.status_code == 200
        import re

        match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        assert match is not None
        return match.group(1)

    def test_login_get_returns_login_page(self, sync_client):
        response = sync_client.get("/login")
        assert response.status_code == 200
        assert "login" in response.text.lower()

    def test_login_with_valid_credentials(self, sync_client, test_user):
        csrf_token = self._csrf_token(sync_client)
        response = sync_client.post(
            "/login",
            data={"username": "testuser", "password": "testpassword", "csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/"

    def test_login_with_invalid_username(self, sync_client, test_user):
        csrf_token = self._csrf_token(sync_client)
        response = sync_client.post(
            "/login",
            data={"username": "wronguser", "password": "testpassword", "csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert response.status_code == 401

    def test_login_with_invalid_password(self, sync_client, test_user):
        csrf_token = self._csrf_token(sync_client)
        response = sync_client.post(
            "/login",
            data={"username": "testuser", "password": "wrongpassword", "csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert response.status_code == 401

    def test_logout_clears_session(self, authenticated_client):
        response = authenticated_client.get("/logout", follow_redirects=False)
        assert response.status_code == 302

    def test_protected_route_requires_auth(self, sync_client):
        response = sync_client.get("/")
        assert response.status_code == 200
        assert "sign in" in response.text.lower()

    def test_protected_route_accessible_when_logged_in(self, authenticated_client):
        response = authenticated_client.get("/")
        assert response.status_code == 200
        assert "dashboard" in response.text.lower()

    def test_health_endpoint_works(self, sync_client):
        response = sync_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
