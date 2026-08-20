"""Alembic data migration tests for the precache warming settings flip.

Covers revision 0019_precache_warming_dnsdist: stored settings
rows still equal to the pre-P7 defaults (recursor / 5300) must flip to
the dnsdist edge defaults (dnsdist / 53) when the migration runs, while
user overrides survive, absent rows stay absent (DEFAULTS apply), and
re-running is a no-op.

Unlike the route tests, these drive the real alembic revision chain
(from base) against a dedicated scratch database derived from
TEST_DATABASE_URL, so they exercise the migration SQL exactly as
`alembic upgrade head` executes it on deployment.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command

ADMIN_UI_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_LOCATION = ADMIN_UI_ROOT / "alembic"
PRE_MIGRATION_HEAD = "0018_is_internal"
SCRATCH_DB = "test_powerblockade_alembic"

SERVER_KEY = "precache_dns_server"
PORT_KEY = "precache_dns_port"


def _server_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url or url.startswith("sqlite"):
        pytest.skip("requires a PostgreSQL TEST_DATABASE_URL")
    return url


@pytest.fixture()
def alembic_env(monkeypatch):
    """Yield (alembic config, engine) backed by a fresh scratch database.

    Each test gets an empty database with the schema built by the real
    migration chain up to PRE_MIGRATION_HEAD, ready for seeding.
    """
    server = make_url(_server_url())
    admin_engine = create_engine(server.set(database="postgres"))
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{SCRATCH_DB}"'))
    admin_engine.dispose()

    # str(URL) masks the password; env.py needs a usable connection string.
    scratch_url = server.set(database=SCRATCH_DB).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", scratch_url)

    cfg = Config()
    cfg.set_main_option("script_location", str(SCRIPT_LOCATION))
    engine = create_engine(scratch_url)

    command.upgrade(cfg, PRE_MIGRATION_HEAD)

    yield cfg, engine

    engine.dispose()
    admin_engine = create_engine(server.set(database="postgres"))
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)'))
    admin_engine.dispose()


def _seed(engine, rows: dict[str, str]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO settings (key, value) VALUES (:key, :value)"),
            [{"key": k, "value": v} for k, v in rows.items()],
        )


def _setting(engine, key: str) -> str | None:
    with engine.begin() as conn:
        return conn.scalar(text("SELECT value FROM settings WHERE key = :key"), {"key": key})


def _updated_at_is_set(engine, key: str) -> bool:
    with engine.begin() as conn:
        return (
            conn.scalar(
                text("SELECT updated_at IS NOT NULL FROM settings WHERE key = :key"),
                {"key": key},
            )
            is True
        )


@pytest.mark.integration
class TestPrecacheWarmingSettingsMigration:
    def test_old_default_rows_flip(self, alembic_env):
        cfg, engine = alembic_env
        _seed(engine, {SERVER_KEY: "recursor", PORT_KEY: "5300", "timezone": "UTC"})

        command.upgrade(cfg, "head")

        assert _setting(engine, SERVER_KEY) == "dnsdist"
        assert _setting(engine, PORT_KEY) == "53"
        assert _setting(engine, "timezone") == "UTC"
        # The migration bumps updated_at the way set_setting()'s ORM
        # onupdate would; seeded rows start with updated_at NULL.
        assert _updated_at_is_set(engine, SERVER_KEY)
        assert _updated_at_is_set(engine, PORT_KEY)

    def test_user_overrides_survive(self, alembic_env):
        cfg, engine = alembic_env
        _seed(engine, {SERVER_KEY: "unbound.example", PORT_KEY: "5333"})

        command.upgrade(cfg, "head")

        assert _setting(engine, SERVER_KEY) == "unbound.example"
        assert _setting(engine, PORT_KEY) == "5333"
        assert not _updated_at_is_set(engine, SERVER_KEY)
        assert not _updated_at_is_set(engine, PORT_KEY)

    def test_absent_rows_stay_absent(self, alembic_env):
        cfg, engine = alembic_env
        _seed(engine, {"timezone": "Europe/Berlin"})

        command.upgrade(cfg, "head")

        assert _setting(engine, SERVER_KEY) is None
        assert _setting(engine, PORT_KEY) is None
        assert _setting(engine, "timezone") == "Europe/Berlin"

    def test_mixed_combos_resolve_per_key(self, alembic_env):
        """Each key flips independently; the pair is not treated as a unit.

        Deliberate semantics per the P7 handoff: a row flips iff it still
        holds its exact old default, regardless of its sibling row.
        """
        cfg, engine = alembic_env
        # Combo 1: old-default server, already-new-default port.
        _seed(engine, {SERVER_KEY: "recursor", PORT_KEY: "53"})
        command.upgrade(cfg, "head")
        assert _setting(engine, SERVER_KEY) == "dnsdist"
        assert _setting(engine, PORT_KEY) == "53"

        # Combo 2: custom server with a leftover old-default port.
        command.downgrade(cfg, PRE_MIGRATION_HEAD)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM settings"))
        _seed(engine, {SERVER_KEY: "unbound.example", PORT_KEY: "5300"})
        command.upgrade(cfg, "head")
        assert _setting(engine, SERVER_KEY) == "unbound.example"
        assert _setting(engine, PORT_KEY) == "53"

    def test_rerun_is_noop_and_downgrade_reverts(self, alembic_env):
        cfg, engine = alembic_env
        _seed(engine, {SERVER_KEY: "recursor", PORT_KEY: "5300"})

        command.upgrade(cfg, "head")
        assert _setting(engine, SERVER_KEY) == "dnsdist"
        assert _setting(engine, PORT_KEY) == "53"

        # The conditional UPDATEs match zero rows once flipped: the raw
        # statements are safe to re-apply.
        with engine.begin() as conn:
            for key, old, new in ((SERVER_KEY, "recursor", "dnsdist"), (PORT_KEY, "5300", "53")):
                result = conn.execute(
                    text(
                        "UPDATE settings SET value = :new WHERE key = :key AND value = :old"
                    ).bindparams(key=key, old=old, new=new)
                )
                assert result.rowcount == 0

        # Full downgrade/upgrade cycle restores the same end state.
        command.downgrade(cfg, PRE_MIGRATION_HEAD)
        assert _setting(engine, SERVER_KEY) == "recursor"
        assert _setting(engine, PORT_KEY) == "5300"

        command.upgrade(cfg, "head")
        assert _setting(engine, SERVER_KEY) == "dnsdist"
        assert _setting(engine, PORT_KEY) == "53"
