"""Unit tests for config audit service."""

from app.models.blocklist import Blocklist
from app.models.config_change import ConfigChange
from app.services.config_audit import (
    get_entity_history,
    get_recent_changes,
    model_to_dict,
)


class TestGetEntityHistory:
    def test_returns_changes_for_entity_type(self, sync_db_session):
        """Should return all changes for a given entity type."""
        # Create changes for different entity types
        change1 = ConfigChange(
            id=1,
            entity_type="blocklist",
            entity_id=1,
            action="create",
        )
        change2 = ConfigChange(
            id=2,
            entity_type="blocklist",
            entity_id=2,
            action="create",
        )
        change3 = ConfigChange(
            id=3,
            entity_type="forward_zone",
            entity_id=1,
            action="create",
        )
        sync_db_session.add_all([change1, change2, change3])
        sync_db_session.commit()

        blocklist_history = get_entity_history(sync_db_session, "blocklist")

        assert len(blocklist_history) == 2
        assert all(c.entity_type == "blocklist" for c in blocklist_history)

    def test_filters_by_entity_id(self, sync_db_session):
        """Should filter by specific entity_id when provided."""
        change1 = ConfigChange(
            id=1,
            entity_type="blocklist",
            entity_id=1,
            action="create",
        )
        change2 = ConfigChange(
            id=2,
            entity_type="blocklist",
            entity_id=1,
            action="update",
        )
        change3 = ConfigChange(
            id=3,
            entity_type="blocklist",
            entity_id=2,
            action="create",
        )
        sync_db_session.add_all([change1, change2, change3])
        sync_db_session.commit()

        history = get_entity_history(sync_db_session, "blocklist", entity_id=1)

        assert len(history) == 2
        assert all(c.entity_id == 1 for c in history)

    def test_respects_limit(self, sync_db_session):
        """Should respect the limit parameter."""
        for i in range(10):
            change = ConfigChange(
                id=i + 1,
                entity_type="blocklist",
                entity_id=i + 1,
                action="create",
            )
            sync_db_session.add(change)
        sync_db_session.commit()

        history = get_entity_history(sync_db_session, "blocklist", limit=5)

        assert len(history) == 5

    def test_orders_by_created_at_desc(self, sync_db_session):
        """Should order results by created_at descending (newest first)."""
        # Create changes in order
        for i in range(3):
            change = ConfigChange(
                id=i + 1,
                entity_type="blocklist",
                entity_id=i + 1,
                action="create",
            )
            sync_db_session.add(change)
            sync_db_session.commit()

        history = get_entity_history(sync_db_session, "blocklist")

        # Newest (highest id) should be first
        assert history[0].id == 3


class TestGetRecentChanges:
    def test_returns_all_recent_changes(self, sync_db_session):
        """Should return changes across all entity types."""
        change1 = ConfigChange(
            id=1,
            entity_type="blocklist",
            entity_id=1,
            action="create",
        )
        change2 = ConfigChange(
            id=2,
            entity_type="forward_zone",
            entity_id=1,
            action="create",
        )
        change3 = ConfigChange(
            id=3,
            entity_type="node",
            entity_id=1,
            action="update",
        )
        sync_db_session.add_all([change1, change2, change3])
        sync_db_session.commit()

        changes = get_recent_changes(sync_db_session)

        assert len(changes) == 3
        entity_types = {c.entity_type for c in changes}
        assert entity_types == {"blocklist", "forward_zone", "node"}

    def test_respects_limit(self, sync_db_session):
        """Should respect the limit parameter."""
        for i in range(20):
            change = ConfigChange(
                id=i + 1,
                entity_type="blocklist",
                entity_id=i + 1,
                action="create",
            )
            sync_db_session.add(change)
        sync_db_session.commit()

        changes = get_recent_changes(sync_db_session, limit=10)

        assert len(changes) == 10

    def test_returns_empty_list_when_no_changes(self, sync_db_session):
        """Should return empty list when no changes exist."""
        changes = get_recent_changes(sync_db_session)
        assert changes == []


class TestModelToDict:
    def test_converts_model_to_dict(self, sync_db_session):
        """Should convert SQLAlchemy model to dictionary."""
        blocklist = Blocklist(
            id=1,
            url="https://example.com/list.txt",
            name="Test List",
            format="hosts",
            list_type="block",
            enabled=True,
        )
        sync_db_session.add(blocklist)
        sync_db_session.commit()

        result = model_to_dict(blocklist)

        assert result["url"] == "https://example.com/list.txt"
        assert result["name"] == "Test List"
        assert result["format"] == "hosts"
        assert result["list_type"] == "block"
        assert result["enabled"] is True

    def test_excludes_sa_instance_state(self, sync_db_session):
        """Should not include SQLAlchemy internal state."""
        blocklist = Blocklist(
            id=1,
            url="https://example.com/list.txt",
            name="Test List",
            format="hosts",
            list_type="block",
            enabled=True,
        )
        sync_db_session.add(blocklist)
        sync_db_session.commit()

        result = model_to_dict(blocklist)

        assert "_sa_instance_state" not in result

    def test_excludes_specified_keys(self, sync_db_session):
        """Should exclude keys specified in exclude set."""
        blocklist = Blocklist(
            id=1,
            url="https://example.com/list.txt",
            name="Test List",
            format="hosts",
            list_type="block",
            enabled=True,
        )
        sync_db_session.add(blocklist)
        sync_db_session.commit()

        result = model_to_dict(blocklist, exclude={"id", "url"})

        assert "id" not in result
        assert "url" not in result
        assert "name" in result

    def test_excludes_private_attributes(self, sync_db_session):
        """Should not include attributes starting with underscore."""
        blocklist = Blocklist(
            id=1,
            url="https://example.com/list.txt",
            name="Test List",
            format="hosts",
            list_type="block",
            enabled=True,
        )
        sync_db_session.add(blocklist)
        sync_db_session.commit()

        result = model_to_dict(blocklist)

        # No keys should start with underscore
        assert not any(k.startswith("_") for k in result.keys())

    def test_excludes_callable_attributes(self, sync_db_session):
        """Should not include methods/callables."""
        blocklist = Blocklist(
            id=1,
            url="https://example.com/list.txt",
            name="Test List",
            format="hosts",
            list_type="block",
            enabled=True,
        )
        sync_db_session.add(blocklist)
        sync_db_session.commit()

        result = model_to_dict(blocklist)

        # All values should not be callable
        assert not any(callable(v) for v in result.values())
