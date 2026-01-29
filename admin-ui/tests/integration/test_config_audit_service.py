"""Integration tests for config audit service.

Tests for record_change require PostgreSQL because ConfigChange model uses BigInteger
primary key without explicit ID assignment, relying on auto-increment (SERIAL).
"""

import pytest

from app.models.config_change import ConfigChange
from app.models.user import User
from app.services.config_audit import record_change


@pytest.mark.integration
class TestRecordChange:
    def test_creates_change_record(self, pg_session):
        change = record_change(
            pg_session,
            entity_type="blocklist",
            entity_id=1,
            action="create",
            comment="Added new blocklist",
        )
        pg_session.commit()

        assert change.id is not None
        assert change.entity_type == "blocklist"
        assert change.entity_id == 1
        assert change.action == "create"
        assert change.comment == "Added new blocklist"

    def test_stores_before_and_after_data(self, pg_session):
        before = {"name": "Old List", "enabled": True}
        after = {"name": "New List", "enabled": False}

        record_change(
            pg_session,
            entity_type="blocklist",
            entity_id=1,
            action="update",
            before_data=before,
            after_data=after,
        )
        pg_session.commit()

        retrieved = pg_session.query(ConfigChange).first()
        assert retrieved.before_data == before
        assert retrieved.after_data == after

    def test_records_actor_user_id(self, pg_session):
        user = User(id=1, username="admin", password_hash="hash")
        pg_session.add(user)
        pg_session.commit()

        change = record_change(
            pg_session,
            entity_type="forward_zone",
            entity_id=5,
            action="delete",
            actor_user_id=user.id,
        )
        pg_session.commit()

        assert change.actor_user_id == user.id

    def test_allows_null_entity_id(self, pg_session):
        change = record_change(
            pg_session,
            entity_type="settings",
            entity_id=None,
            action="update",
            after_data={"retention_days": 90},
        )
        pg_session.commit()

        assert change.entity_id is None

    def test_allows_null_actor_user_id(self, pg_session):
        change = record_change(
            pg_session,
            entity_type="node",
            entity_id=1,
            action="create",
        )
        pg_session.commit()

        assert change.actor_user_id is None
