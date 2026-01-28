"""
Pytest fixtures for PowerBlockade admin-ui tests.

This module provides fixtures for both unit tests (in-memory SQLite) and
integration tests (PostgreSQL). Most tests should use the sync fixtures
(sync_db_session, sync_client) for simplicity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User


def _sqlite_now():
    return datetime.now(timezone.utc).isoformat()


def _setup_sqlite_now(dbapi_conn, connection_record):
    dbapi_conn.create_function("NOW", 0, _sqlite_now)


# Test database URL (PostgreSQL for integration tests)
TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/test_powerblockade"


@pytest.fixture(scope="session")
def pg_engine():
    """Create PostgreSQL engine for integration tests."""
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine) -> Generator[Session, None, None]:
    """Create a PostgreSQL session for integration tests."""
    TestSession = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    session = TestSession()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def pg_client(pg_session) -> Generator[TestClient, None, None]:
    """Create test client with PostgreSQL dependency override."""

    def override_get_db():
        yield pg_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sync_db_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _setup_sqlite_now)
    Base.metadata.create_all(engine)

    TestSession = sessionmaker(bind=engine)
    session = TestSession()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def sync_client(sync_db_session):
    """Create test client with sync DB dependency override."""

    def override_get_db():
        yield sync_db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(sync_db_session):
    """Create a test user for authentication."""
    from app.security import hash_password

    user = User(username="testuser", password_hash=hash_password("testpassword"))
    sync_db_session.add(user)
    sync_db_session.commit()
    sync_db_session.refresh(user)
    return user


@pytest.fixture
def authenticated_client(sync_client, test_user):
    _ = test_user
    sync_client.post(
        "/login",
        data={"username": "testuser", "password": "testpassword"},
        follow_redirects=False,
    )
    return sync_client


@pytest.fixture
def sample_blocklist_data():
    """Return sample blocklist data for testing."""
    return [
        {
            "url": "https://example.com/ads.txt",
            "name": "Test Ads List",
            "list_type": "block",
            "enabled": True,
        },
        {
            "url": "https://example.com/malware.txt",
            "name": "Test Malware List",
            "list_type": "block",
            "enabled": True,
        },
    ]


@pytest.fixture
def sample_forward_zone_data():
    """Return sample forward zone data for testing."""
    return [
        {
            "name": "internal.corp.local",
            "nameservers": "10.0.1.53,10.0.1.54",
            "scope": "global",
            "node_id": None,
        },
        {
            "name": "dev.local",
            "nameservers": "127.0.0.1:5353",
            "scope": "global",
            "node_id": None,
        },
    ]


# Playwright fixtures
@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Set browser context args for Playwright."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
    }
