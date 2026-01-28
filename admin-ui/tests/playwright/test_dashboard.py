"""E2E Playwright tests for dashboard and analytics."""

import pytest


class TestDashboard:
    def test_dashboard_loads_when_authenticated(self, authenticated_page):
        authenticated_page.goto("/")
        assert "dashboard" in authenticated_page.content().lower()

    def test_dashboard_shows_stats_cards(self, authenticated_page):
        authenticated_page.goto("/")

        cards = authenticated_page.locator(".rounded-xl.border.border-slate-800")
        assert cards.count() >= 4

    def test_metrics_link_works(self, authenticated_page):
        authenticated_page.goto("/")

        with authenticated_page.expect_response("**/metrics") as response_info:
            authenticated_page.click("text=Prometheus metrics")

        assert response_info.value.status == 200

    def test_logs_page_loads(self, authenticated_page):
        authenticated_page.goto("/logs")
        assert "logs" in authenticated_page.content().lower()

    def test_clients_page_loads(self, authenticated_page):
        authenticated_page.goto("/clients")
        assert "clients" in authenticated_page.content().lower()

    def test_blocked_page_loads(self, authenticated_page):
        authenticated_page.goto("/blocked")
        assert "blocked" in authenticated_page.content().lower()

    def test_precache_link_works(self, authenticated_page):
        authenticated_page.goto("/")
        authenticated_page.click('a[href="/precache"]')
        authenticated_page.wait_for_load_state()
        assert "precache" in authenticated_page.content().lower()


@pytest.fixture
def authenticated_page(page, test_user):
    page.goto("/login")
    page.fill('input[name="username"]', "testuser")
    page.fill('input[name="password"]', "testpassword")
    page.click('button[type="submit"]')
    page.wait_for_url("/")
    return page
