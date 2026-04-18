"""Unit tests for atomic_write and safe_write utilities."""

import os
from unittest.mock import patch

import pytest

from app.services.atomic_write import atomic_write, safe_write


class TestAtomicWrite:
    """Tests for atomic_write (temp + os.replace)."""

    def test_happy_path_writes_content(self, tmp_path):
        dest = tmp_path / "zone.rpz"
        atomic_write(str(dest), "zone content here")

        assert dest.read_text() == "zone content here"

    def test_replaces_existing_file(self, tmp_path):
        dest = tmp_path / "zone.rpz"
        dest.write_text("old content")
        atomic_write(str(dest), "new content")

        assert dest.read_text() == "new content"

    def test_creates_parent_directory(self, tmp_path):
        dest = tmp_path / "subdir" / "nested" / "zone.rpz"
        atomic_write(str(dest), "deeply nested")

        assert dest.read_text() == "deeply nested"

    def test_cleanup_on_failure_removes_temp_file(self, tmp_path):
        dest = tmp_path / "zone.rpz"

        with patch("app.services.atomic_write.os.replace", side_effect=PermissionError("nope")):
            with pytest.raises(PermissionError, match="nope"):
                atomic_write(str(dest), "will fail")

        tmp_files = list(tmp_path.iterdir())
        assert len(tmp_files) == 0

    def test_writes_utf8_content(self, tmp_path):
        dest = tmp_path / "zone.rpz"
        atomic_write(str(dest), "über域名")

        assert dest.read_text(encoding="utf-8") == "über域名"


class TestSafeWrite:
    """Tests for safe_write (temp + copy, preserves inode)."""

    def test_happy_path_writes_content(self, tmp_path):
        dest = tmp_path / "forward-zones.conf"
        safe_write(str(dest), "corp.local=10.0.1.53")

        assert dest.read_text() == "corp.local=10.0.1.53"

    def test_updates_existing_file_content(self, tmp_path):
        dest = tmp_path / "forward-zones.conf"
        dest.write_text("old content")
        safe_write(str(dest), "new content")

        assert dest.read_text() == "new content"

    def test_preserves_inode(self, tmp_path):
        """safe_write must NOT change the inode — critical for Docker file bind mounts."""
        dest = tmp_path / "forward-zones.conf"
        dest.write_text("original")
        original_inode = os.stat(dest).st_ino

        safe_write(str(dest), "updated")

        assert os.stat(dest).st_ino == original_inode
        assert dest.read_text() == "updated"

    def test_creates_parent_directory(self, tmp_path):
        dest = tmp_path / "nested" / "dir" / "forward-zones.conf"
        safe_write(str(dest), "content")

        assert dest.read_text() == "content"

    def test_cleanup_removes_temp_file(self, tmp_path):
        dest = tmp_path / "forward-zones.conf"

        safe_write(str(dest), "hello")

        tmp_files = [f for f in tmp_path.iterdir() if f.name.startswith(".pb-tmp-")]
        assert len(tmp_files) == 0

    def test_cleanup_removes_temp_file_on_failure(self, tmp_path):
        dest = tmp_path / "forward-zones.conf"

        original_open = open
        call_count = 0

        def failing_open(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # open() is called twice in safe_write:
            #   1st = read-back from temp, 2nd = in-place write to destination.
            # Fail on the 2nd call to exercise the finally-cleanup path.
            if call_count == 2:
                raise OSError("disk full")
            return original_open(*args, **kwargs)

        with patch("builtins.open", side_effect=failing_open):
            with pytest.raises(OSError, match="disk full"):
                safe_write(str(dest), "will fail")

        tmp_files = [f for f in tmp_path.iterdir() if f.name.startswith(".pb-tmp-")]
        assert len(tmp_files) == 0

    def test_writes_utf8_content(self, tmp_path):
        dest = tmp_path / "forward-zones.conf"
        safe_write(str(dest), "über域名")

        assert dest.read_text(encoding="utf-8") == "über域名"
