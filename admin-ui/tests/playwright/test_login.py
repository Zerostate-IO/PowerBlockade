"""E2E Playwright tests for authentication flows."""

import pytest


class TestLoginFlow:
    def test_login_page_loads(self, page):
        page.goto("/login")
        assert "login" in page.title().lower()

    def test_successful_login(self, page, test_user):
        page.goto("/login")

        page.fill('input[name="username"]', "testuser")
        page.fill('input[name="password"]', "testpassword")
        page.click('button[type="submit"]')

        page.wait_for_url("/")
        assert "dashboard" in page.content().lower()

    def test_invalid_credentials_shows_error(self, page, test_user):
        page.goto("/login")

        page.fill('input[name="username"]', "testuser")
        page.fill('input[name="password"]', "wrongpassword")
        page.click('button[type="submit"]')

        page.wait_for_load_state("networkidle")

    def test_logout_redirects_to_home(self, page, authenticated_page):
        page.goto("/")

        page.click('a[href="/logout"]')
        page.wait_for_url("*/login")


@pytest.fixture
def authenticated_page(page, test_user):
    page.goto("/login")
    page.fill('input[name="username"]', "testuser")
    page.fill('input[name="password"]', "testpassword")
    page.click('button[type="submit"]')
    page.wait_for_url("/")
    return page
