"""Unit tests for /api/version endpoint authentication."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


class TestVersionEndpointAuth:
    def test_version_requires_authentication(self, sync_client):
        response = sync_client.get("/api/version")
        assert response.status_code == 401
        assert "Authentication required" in response.text

    def test_version_returns_data_when_authenticated(self, sync_client):
        # Login to get authenticated session
        sync_client.post("/login", data={"username": "testuser", "password": "testpassword"})

        response = sync_client.get("/api/version")
        assert response.status_code == 200

        data = response.json()
        assert "version" in data
        assert "git_sha" in data
        assert "build_date" in data
        assert "api_protocol_version" in data
        assert "api_protocol_min_supported" in data
