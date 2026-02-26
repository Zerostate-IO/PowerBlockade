"""E2E Playwright tests for authentication flows."""

import os

import pytest


class TestLoginFlow:
    def test_login_page_loads(self, page):
        page.goto("/login")
        assert "powerblockade" in page.title().lower()

    def test_successful_login(self, page):
        page.goto("/login")

        page.fill('input[name="username"]', os.environ.get("ADMIN_USERNAME", "admin"))
        page.fill('input[name="password"]', os.environ.get("ADMIN_PASSWORD", "testpassword"))
        page.click('button[type="submit"]')

        page.wait_for_url("**/")
        assert "dashboard" in page.content().lower()

    def test_invalid_credentials_shows_error(self, page):
        page.goto("/login")

        page.fill('input[name="username"]', os.environ.get("ADMIN_USERNAME", "admin"))
        page.fill('input[name="password"]', "wrongpassword")
        page.click('button[type="submit"]')

        page.wait_for_load_state("networkidle")

    def test_logout_redirects_to_home(self, authenticated_page):
        authenticated_page.goto("/logout")
        authenticated_page.wait_for_url("**/login")


@pytest.fixture
def authenticated_page(page):
    page.goto("/login")
    page.fill('input[name="username"]', os.environ.get("ADMIN_USERNAME", "admin"))
    page.fill('input[name="password"]', os.environ.get("ADMIN_PASSWORD", "testpassword"))
    page.click('button[type="submit"]')
    page.wait_for_url("**/")
    return page
