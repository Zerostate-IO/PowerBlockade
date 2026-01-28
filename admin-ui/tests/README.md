# Testing Documentation

This directory contains the test suite for PowerBlockade admin-ui.

## Structure

```
tests/
├── conftest.py           # Pytest fixtures and configuration
├── unit/                 # Unit tests (fast, no external deps)
│   ├── test_security.py   # Password hashing and verification
│   ├── test_models.py     # SQLAlchemy model tests
│   ├── test_rpz_service.py # RPZ blocklist parsing
│   └── test_forward_zones_service.py # Config generation
├── integration/           # Integration tests (require database)
│   ├── test_auth_routes.py      # Login/logout flows
│   ├── test_blocklist_routes.py # CRUD and Apply endpoints
│   ├── test_forward_zones_routes.py # Forward zones CRUD
│   ├── test_analytics_routes.py  # Dashboard and analytics pages
│   └── test_node_sync_routes.py  # API endpoints for nodes
└── playwright/            # E2E browser tests
    ├── test_login.py       # Authentication flows
    ├── test_dashboard.py   # Dashboard and analytics rendering
    ├── test_blocklists.py  # Blocklist management UI
    └── test_forward_zones.py # Forward zones management UI

```

## Running Tests

### Unit Tests
```bash
cd admin-ui
uv run pytest tests/unit/ -v
```

### Integration Tests
```bash
cd admin-ui
uv run pytest tests/integration/ -v -m integration
```

### All Tests
```bash
cd admin-ui
uv run pytest -v
```

### Playwright Tests
```bash
cd admin-ui
uv run pytest -m playwright --headless
```

### Run with Coverage
```bash
cd admin-ui
uv run pytest --cov=app --cov-report=html -v
```

## Test Markers

- `unit`: Unit tests that don't require external dependencies
- `integration`: Tests requiring database integration
- `e2e`: End-to-end tests requiring full stack
- `playwright`: Browser automation tests

## Adding New Tests

1. Unit tests go in `tests/unit/`
2. Integration tests go in `tests/integration/`
3. Playwright tests go in `tests/playwright/`

Use existing test fixtures from `conftest.py`:
- `sync_db_session`: SQLite in-memory session for fast tests
- `test_user`: Pre-created test user for authentication
- `authenticated_client`: Test client with logged-in session
- `page` / `authenticated_page`: Playwright page objects

## Notes

- Unit tests use SQLite in-memory for speed
- Integration tests support PostgreSQL for more accurate testing
- Playwright tests require Playwright browsers installed: `playwright install`
- Fixtures automatically create test users and sessions