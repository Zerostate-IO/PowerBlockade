# PowerBlockade Testing Plan

## Overview

This document outlines the testing strategy for PowerBlockade admin-ui with comprehensive unit, integration, and end-to-end (E2E) browser tests.

## Test Categories

### 1. Unit Tests (`tests/unit/`)
Fast tests focusing on individual functions and methods without external dependencies.

**Coverage:**
- `test_security.py`: Password hashing, verification, pre-hashing logic
- `test_models.py`: SQLAlchemy models (User, Blocklist, ForwardZone, DNSQueryEvent, Client, Node)
- `test_rpz_service.py`: RPZ blocklist parsing (hosts, domains, adblock formats)
- `test_forward_zones_service.py`: Config generation, global vs per-node filtering

**Database:** SQLite in-memory (fast startup)
**Runtime:** < 1s per test
**Command:** `uv run pytest tests/unit/ -v`

### 2. Integration Tests (`tests/integration/`)
Tests for API endpoints and routes requiring database integration.

**Coverage:**
- `test_auth_routes.py`: Login/logout flows, protected routes
- `test_blocklist_routes.py`: CRUD operations and Apply endpoint
- `test_forward_zones_routes.py`: CRUD operations and config generation
- `test_analytics_routes.py`: Dashboard, metrics endpoint
- `test_node_sync_routes.py`: Register, heartbeat, ingest API endpoints

**Database:** PostgreSQL (test database)
**Runtime:** 2-5s per test
**Command:** `uv run pytest tests/integration/ -v -m integration`

### 3. E2E Browser Tests (`tests/playwright/`)
Real browser automation testing the full user interface.

**Coverage:**
- `test_login.py`: Login page, successful login, logout flow
- `test_dashboard.py`: Dashboard rendering, stats cards, metrics endpoint
- `test_blocklists.py`: Blocklist management UI, add/create/apply flows
- `test_forward_zones.py`: Forward zones UI, creation, apply

**Browser:** Chromium (Headless in CI)
**Runtime:** 5-15s per test
**Command:** `uv run pytest tests/playwright/ -v -m playwright --headless`

## Test Fixtures

### From `tests/conftest.py`:

- `sync_db_session`: SQLite in-memory session for fast unit tests
- `async_db_session`: Async PostgreSQL session for integration tests
- `syn_client` / `async_client`: FastAPI TestClient with dependency overrides
- `test_user`: Pre-created test user (username: "testuser", password: "testpassword")
- `authenticated_client`: Test client with logged-in session
- `page` / `authenticated_page`: Playwright page objects

## Running Tests Locally

```bash
cd admin-ui

# Unit tests only
uv run pytest tests/unit/ -v

# Integration tests
uv run pytest tests/integration/ -v -m integration

# All tests
uv run pytest -v

# Playwright tests
uv run pytest tests/playwright/ -v -m playwright --headless

# With coverage
uv run pytest --cov=app --cov-report=html -v
```

## CI/CD Pipeline

The `.github/workflows/tests.yml` workflow runs:

1. **Unit Tests** - Fast feedback loop, checks core logic
2. **Integration Tests** - Validates database interactions and API contracts
3. **Playwright Tests** - E2E validation of critical user flows
4. **Lint** - Code quality (ruff check + format)

## Test Priorities

| Priority | Type | Description |
|----------|------|-------------|
| P0 | Unit | Security (password hashing), Models |
| P0 | Integration | Auth, Node Sync API, Routes |
| P1 | Playwright | Login flow, Dashboard, Blocklists |
| P2 | Integration | Stats calculations |
| P2 | Playwright | Forward zones, Help pages |

## Adding New Tests

1. **Unit Test:** Create in `tests/unit/`, use `sync_db_session` or pure Python
2. **Integration Test:** Create in `tests/integration/`, use `authenticated_client`
3. **Playwright Test:** Create in `tests/playwright/`, use `page` and `authenticated_page`

Follow existing patterns:
- Use descriptive test names (`test_<when>_<under_what_conditions>`)
- Arrange-Act-Assert pattern
- Reuse fixtures from `conftest.py`

## Expected Test Counts

- Unit tests: ~30 tests
- Integration tests: ~25 tests
- Playwright tests: ~15 tests
- Total: ~70 tests

## Notes

- Unit tests use SQLite for speed; integration tests use PostgreSQL for accuracy
- Playwright requires browser install: `uv run playwright install`
- Fixtures automatically handle test cleanup and session management
- All tests are independent and can run in parallel