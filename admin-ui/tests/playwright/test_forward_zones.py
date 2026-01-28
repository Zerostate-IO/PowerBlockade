"""E2E Playwright tests for forward zones management."""

import pytest


class TestForwardZonesManagement:
    def test_forward_zones_page_loads(self, authenticated_page):
        authenticated_page.goto("/forwardzones")
        assert "forward" in authenticated_page.content().lower()

    def test_create_forward_zone(self, authenticated_page):
        authenticated_page.goto("/forwardzones")

        authenticated_page.click("text=Add Forward Zone")

        authenticated_page.fill('input[name="name"]', "test.local")
        authenticated_page.fill('input[name="nameservers"]', "10.0.1.1")
        authenticated_page.click('button[type="submit"]')

        authenticated_page.wait_for_url("**/forwardzones")

    def test_apply_button_exists(self, authenticated_page):
        authenticated_page.goto("/forwardzones")

        apply_button = authenticated_page.locator('button:has-text("Apply")')
        assert apply_button.is_visible()


@pytest.fixture
def authenticated_page(page, test_user):
    page.goto("/login")
    page.fill('input[name="username"]', "testuser")
    page.fill('input[name="password"]', "testpassword")
    page.click('button[type="submit"]')
    page.wait_for_url("/")
    return page
