"""
Pytest fixtures for PowerBlockade admin-ui tests.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

# Import these after we have a proper test environment
from app.db.session import Base, get_db
from app.main import app
from app.models.blocklist import Blocklist
from app.models.forward_zone import ForwardZone
from app.models.user import User


# Test database URL (PostgreSQL for integration tests)
TEST_DATABASE_URL = (
    "postgresql+psycopg://postgres:postgres@localhost:5432/test_powerblockade"
)


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def async_engine():
    """Create async engine for test database."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )
    yield engine
    engine.dispose()


@pytest.fixture
async def db_session(async_engine) -> AsyncIterator[AsyncSession]:
    """Create a fresh database session for each test."""
    # Create tables
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session
    async_session = sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session
        await session.rollback()


@pytest.fixture
def db(db_session):
    """Sync wrapper around async db_session for compatibility."""
    # For now, return None - tests will need to use async patterns
    # or we use the synchronous version
    return None


@pytest.fixture
def client(db_session):
    """Create a test client with test database dependency override."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sync_db_session():
    """Use in-memory SQLite for sync tests without PostgreSQL."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Use in-memory SQLite for fast unit tests
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

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
    """Create a test client with authenticated session."""
    # Login to establish session
    response = sync_client.post(
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
