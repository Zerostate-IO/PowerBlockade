"""E2E Playwright tests for blocklist management."""

import pytest


class TestBlocklistManagement:
    def test_blocklist_page_loads(self, authenticated_page):
        authenticated_page.goto("/blocklists")
        assert "blocklist" in authenticated_page.content().lower()

    def test_create_blocklist(self, authenticated_page):
        authenticated_page.goto("/blocklists")

        authenticated_page.click("text=Add Blocklist")

        authenticated_page.fill('input[name="url"]', "https://example.com/test.txt")
        authenticated_page.fill('input[name="name"]', "Test List")
        authenticated_page.select_option('select[name="list_type"]', "block")
        authenticated_page.click('button[type="submit"]')

        authenticated_page.wait_for_url("**/blocklists")

    def test_apply_button_exists(self, authenticated_page):
        authenticated_page.goto("/blocklists")

        apply_button = authenticated_page.locator('button:has-text("Apply")')
        assert apply_button.is_visible()

    def test_help_link_works(self, authenticated_page):
        authenticated_page.goto("/help")

        help_topics = authenticated_page.locator('a[href^="/help/"]')
        assert help_topics.count() >= 4


@pytest.fixture
def authenticated_page(page, test_user):
    page.goto("/login")
    page.fill('input[name="username"]', "testuser")
    page.fill('input[name="password"]', "testpassword")
    page.click('button[type="submit"]')
    page.wait_for_url("/")
    return page
