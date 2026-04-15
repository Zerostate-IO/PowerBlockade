"""Unit tests for RPZ atomic write paths in blocklists, scheduler, and blocking.

Validates that the three primary RPZ writers (manual apply, scheduled
regeneration, emergency blocking) produce correct RPZ zone files via
``atomic_write()`` and preserve expected filenames and content semantics.
"""

from __future__ import annotations

import os
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from app.services.atomic_write import atomic_write
from app.services.rpz import render_rpz_whitelist, render_rpz_zone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_file(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. atomic_write integration with RPZ rendering
# ---------------------------------------------------------------------------


class TestAtomicWriteRPZContent:
    """Verify that atomic_write + render_rpz_* produces valid RPZ files."""

    def test_blocked_zone_file_content(self, tmp_path):
        blocked = {"ads.example.com", "tracker.example.com"}
        content = render_rpz_zone(blocked, policy_name="blocklist-combined")
        rpz_path = str(tmp_path / "blocklist-combined.rpz")
        atomic_write(rpz_path, content)

        text = _read_file(rpz_path)
        assert "$TTL 300" in text
        assert "SOA localhost." in text
        assert "ads.example.com. CNAME ." in text
        assert "tracker.example.com. CNAME ." in text
        assert "; policy: blocklist-combined" in text

    def test_whitelist_zone_file_content(self, tmp_path):
        allowed = {"safe.example.com", "ok.example.com"}
        content = render_rpz_whitelist(allowed)
        rpz_path = str(tmp_path / "whitelist.rpz")
        atomic_write(rpz_path, content)

        text = _read_file(rpz_path)
        assert "$TTL 300" in text
        assert "safe.example.com. CNAME rpz-passthru." in text
        assert "ok.example.com. CNAME rpz-passthru." in text
        assert "; whitelist (rpz-passthru)" in text

    def test_empty_blocked_set_still_produces_header(self, tmp_path):
        content = render_rpz_zone(set(), policy_name="blocklist-combined")
        rpz_path = str(tmp_path / "blocklist-combined.rpz")
        atomic_write(rpz_path, content)

        text = _read_file(rpz_path)
        assert "$TTL 300" in text
        assert "SOA localhost." in text
        # No CNAME lines for empty domain set
        assert "CNAME" not in text

    def test_atomic_write_replaces_existing_file(self, tmp_path):
        rpz_path = str(tmp_path / "blocklist-combined.rpz")
        atomic_write(rpz_path, "old content")
        assert _read_file(rpz_path) == "old content"

        atomic_write(rpz_path, "new content")
        assert _read_file(rpz_path) == "new content"

    def test_no_temp_files_left_behind(self, tmp_path):
        rpz_path = str(tmp_path / "blocklist-combined.rpz")
        atomic_write(rpz_path, render_rpz_zone({"x.com"}, policy_name="test"))
        temp_files = [f for f in os.listdir(str(tmp_path)) if f.startswith(".pb-tmp-")]
        assert temp_files == []


# ---------------------------------------------------------------------------
# 2. blocklists_apply route uses atomic_write
# ---------------------------------------------------------------------------


class TestBlocklistsApplyAtomicWrite:
    """Verify blocklists_apply writes RPZ files via atomic_write."""

    @patch("app.routers.blocklists.fetch_and_parse_blocklist")
    def test_apply_writes_rpz_files_via_atomic_write(self, mock_fetch, tmp_path):
        """Integration-level test: blocklists_apply produces correct RPZ output."""
        mock_fetch.return_value = {"ads.example.com", "malware.example.com"}

        rpz_dir = str(tmp_path / "rpz")

        from app.models.blocklist import Blocklist
        from app.models.manual_entry import ManualEntry

        # Build a minimal DB session mock
        mock_db = MagicMock()

        bl = Blocklist(
            url="https://example.com/list.txt",
            name="Test Block",
            format="domains",
            list_type="block",
            enabled=True,
        )
        bl.id = 1

        allow_entry = ManualEntry(domain="safe.example.com", entry_type="allow")
        allow_entry.id = 1

        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [bl],  # enabled blocklists
            [allow_entry],  # allow entries
            [],  # block entries (empty)
        ]
        mock_db.query.return_value.filter.return_value.filter.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.delete.return_value = None

        with patch.dict(os.environ, {"POWERBLOCKADE_SHARED_DIR": str(tmp_path)}):
            from app.routers.blocklists import blocklists_apply

            # We need a Request mock but the function signature is simple
            mock_request = MagicMock()
            mock_request.headers.get.return_value = ""

            # Create a user mock for auth
            mock_user = MagicMock()
            mock_user.id = 1

            # Patch get_current_user to return our mock user
            with patch("app.routers.blocklists.get_current_user", return_value=mock_user):
                with patch("app.routers.blocklists.get_setting", return_value="UTC"):
                    with patch("app.routers.blocklists.get_templates") as mock_tmpl:
                        mock_tmpl.return_value.TemplateResponse.return_value = MagicMock()
                        blocklists_apply(mock_request, mock_db)

        # Verify RPZ files were written atomically (no temp files)
        rpz_files = os.listdir(rpz_dir)
        assert "blocklist-combined.rpz" in rpz_files
        assert "whitelist.rpz" in rpz_files
        temp_files = [f for f in rpz_files if f.startswith(".pb-tmp-")]
        assert temp_files == []

        # Verify content correctness
        blocked_text = _read_file(os.path.join(rpz_dir, "blocklist-combined.rpz"))
        assert "ads.example.com. CNAME ." in blocked_text
        assert "malware.example.com. CNAME ." in blocked_text
        # safe.example.com should NOT be blocked (it's in whitelist)
        assert "safe.example.com. CNAME ." not in blocked_text

        whitelist_text = _read_file(os.path.join(rpz_dir, "whitelist.rpz"))
        assert "safe.example.com. CNAME rpz-passthru." in whitelist_text


# ---------------------------------------------------------------------------
# 3. regenerate_rpz (scheduler) uses atomic_write
# ---------------------------------------------------------------------------


class TestRegenerateRPZAtomicWrite:
    """Verify regenerate_rpz writes RPZ files via atomic_write."""

    def test_regenerate_writes_both_rpz_files(self, tmp_path):

        from app.models.blocklist import Blocklist
        from app.models.manual_entry import ManualEntry

        mock_db = MagicMock()

        bl = Blocklist(
            url="https://example.com/list.txt",
            name="Test",
            format="domains",
            list_type="block",
            enabled=True,
        )
        bl.id = 1

        block_entry = ManualEntry(domain="manual-block.com", entry_type="block")
        block_entry.id = 1

        allow_entry = ManualEntry(domain="allow.example.com", entry_type="allow")
        allow_entry.id = 2

        bl_entry = MagicMock()
        bl_entry.domain = "scheduler-blocked.com"

        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [bl],
            [allow_entry],
            [block_entry],
            [bl_entry],
        ]
        mock_db.query.return_value.filter.return_value.filter.return_value.all.return_value = [
            bl_entry
        ]

        rpz_dir_str = str(tmp_path / "rpz")
        os.makedirs(rpz_dir_str, exist_ok=True)

        _real_join = os.path.join
        _blocked_path = _real_join(rpz_dir_str, "blocklist-combined.rpz")
        _whitelist_path = _real_join(rpz_dir_str, "whitelist.rpz")

        def _redirected_join(*args):
            if args[-1] == "blocklist-combined.rpz":
                return _blocked_path
            if args[-1] == "whitelist.rpz":
                return _whitelist_path
            return _real_join(*args)

        with patch("app.services.scheduler.os.makedirs"):
            with patch("app.services.scheduler.os.path.join", side_effect=_redirected_join):
                from app.services.scheduler import regenerate_rpz

                regenerate_rpz(mock_db)

        rpz_files = os.listdir(rpz_dir_str)
        assert "blocklist-combined.rpz" in rpz_files
        assert "whitelist.rpz" in rpz_files
        temp_files = [f for f in rpz_files if f.startswith(".pb-tmp-")]
        assert temp_files == []

        blocked_text = _read_file(_blocked_path)
        assert "scheduler-blocked.com. CNAME ." in blocked_text
        assert "manual-block.com. CNAME ." in blocked_text
        assert "allow.example.com. CNAME ." not in blocked_text

        whitelist_text = _read_file(_whitelist_path)
        assert "allow.example.com. CNAME rpz-passthru." in whitelist_text


# ---------------------------------------------------------------------------
# 4. _write_emergency_rpz uses atomic_write
# ---------------------------------------------------------------------------


class TestEmergencyRPZAtomicWrite:
    """Verify _write_emergency_rpz writes via atomic_write."""

    def test_emergency_rpz_uses_atomic_write(self, tmp_path):

        rpz_dir_str = str(tmp_path / "rpz")
        os.makedirs(rpz_dir_str, exist_ok=True)

        _real_join = os.path.join
        _rpz_path = _real_join(rpz_dir_str, "blocklist-combined.rpz")

        def _redirected_join(*args):
            if args[-1] == "blocklist-combined.rpz":
                return _rpz_path
            return _real_join(*args)

        with patch("app.routers.blocking.os.makedirs"):
            with patch("app.routers.blocking.os.path.join", side_effect=_redirected_join):
                from app.routers.blocking import _write_emergency_rpz

                _write_emergency_rpz()

        assert os.path.exists(_rpz_path)

        text = _read_file(_rpz_path)
        assert "$TTL 300" in text
        assert "SOA localhost." in text
        assert "; BLOCKING DISABLED - emergency mode" in text
        assert "CNAME ." not in text

        temp_files = [f for f in os.listdir(rpz_dir_str) if f.startswith(".pb-tmp-")]
        assert temp_files == []

    def test_emergency_rpz_replaces_existing_blocking_zone(self, tmp_path):
        """Emergency write should replace any existing RPZ content."""

        rpz_dir_str = str(tmp_path / "rpz")
        os.makedirs(rpz_dir_str, exist_ok=True)
        rpz_path = os.path.join(rpz_dir_str, "blocklist-combined.rpz")

        atomic_write(rpz_path, render_rpz_zone({"old-block.com"}, policy_name="blocklist-combined"))
        old_text = _read_file(rpz_path)
        assert "old-block.com" in old_text

        _real_join = os.path.join
        _rpz_path = rpz_path

        def _redirected_join(*args):
            if args[-1] == "blocklist-combined.rpz":
                return _rpz_path
            return _real_join(*args)

        with patch("app.routers.blocking.os.makedirs"):
            with patch("app.routers.blocking.os.path.join", side_effect=_redirected_join):
                from app.routers.blocking import _write_emergency_rpz

                _write_emergency_rpz()

        new_text = _read_file(rpz_path)
        assert "old-block.com" not in new_text
        assert "; BLOCKING DISABLED" in new_text
