"""E2E Playwright tests for forward zones management."""

import os

import pytest


class TestForwardZonesManagement:
    def test_forward_zones_page_loads(self, authenticated_page):
        authenticated_page.goto("/forwardzones")
        assert "forward" in authenticated_page.content().lower()

    def test_create_forward_zone(self, authenticated_page):
        authenticated_page.goto("/forwardzones")
        authenticated_page.fill('input[name="domain"]', "test.local")
        authenticated_page.fill('input[name="servers"]', "10.0.1.1")
        authenticated_page.locator('form[action="/forwardzones/add"] button[type="submit"]').click()

        authenticated_page.wait_for_load_state("networkidle")
        assert authenticated_page.locator("text=test.local").first.is_visible()

    def test_apply_button_exists(self, authenticated_page):
        authenticated_page.goto("/forwardzones")

        apply_button = authenticated_page.locator('button:has-text("Apply")')
        assert apply_button.is_visible()


@pytest.fixture
def authenticated_page(page):
    page.goto("/login")
    page.fill('input[name="username"]', os.environ.get("ADMIN_USERNAME", "admin"))
    page.fill('input[name="password"]', os.environ.get("ADMIN_PASSWORD", "testpassword"))
    page.click('button[type="submit"]')
    page.wait_for_url("**/")
    return page
