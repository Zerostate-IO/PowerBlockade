from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import (
    compute_file_checksum,
    get_local_ip,
    get_version,
    getenv_required,
    scrape_recursor_metrics,
    sync_config,
    write_if_changed,
)


class TestGetenvRequired:
    def test_returns_value_when_set(self):
        os.environ["TEST_VAR"] = "test_value"
        try:
            assert getenv_required("TEST_VAR") == "test_value"
        finally:
            del os.environ["TEST_VAR"]

    def test_raises_when_not_set(self):
        if "NONEXISTENT_VAR" in os.environ:
            del os.environ["NONEXISTENT_VAR"]
        with pytest.raises(RuntimeError) as exc_info:
            getenv_required("NONEXISTENT_VAR")
        assert "NONEXISTENT_VAR is required" in str(exc_info.value)

    def test_raises_when_empty(self):
        os.environ["EMPTY_VAR"] = ""
        try:
            with pytest.raises(RuntimeError):
                getenv_required("EMPTY_VAR")
        finally:
            del os.environ["EMPTY_VAR"]


class TestComputeFileChecksum:
    def test_returns_16_char_hex(self):
        result = compute_file_checksum("test content")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_same_content_same_checksum(self):
        content = "hello world"
        assert compute_file_checksum(content) == compute_file_checksum(content)

    def test_different_content_different_checksum(self):
        assert compute_file_checksum("content1") != compute_file_checksum("content2")


class TestWriteIfChanged:
    def test_creates_new_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            result = write_if_changed(filepath, "new content")
            assert result is True
            assert filepath.read_text() == "new content"

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "subdir" / "nested" / "test.txt"
            result = write_if_changed(filepath, "content")
            assert result is True
            assert filepath.exists()

    def test_returns_false_when_content_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            filepath.write_text("existing content")
            result = write_if_changed(filepath, "existing content")
            assert result is False

    def test_returns_true_when_content_changed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            filepath.write_text("old content")
            result = write_if_changed(filepath, "new content")
            assert result is True
            assert filepath.read_text() == "new content"


class TestScrapeRecursorMetrics:
    def test_parses_prometheus_metrics(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """# HELP pdns_recursor_cache_hits Cache hits
# TYPE pdns_recursor_cache_hits counter
pdns_recursor_cache_hits 12345
pdns_recursor_cache_misses 6789
pdns_recursor_cache_entries 1000
pdns_recursor_questions 50000
pdns_recursor_uptime_seconds 3600
pdns_recursor_answers0_1 100
pdns_recursor_answers1_10 200
pdns_recursor_answers10_100 50
pdns_recursor_answers100_1000 10
pdns_recursor_answers_slow 5
"""
        with patch("agent.requests.get", return_value=mock_response):
            result = scrape_recursor_metrics("http://localhost:8082")

        assert result["cache_hits"] == 12345
        assert result["cache_misses"] == 6789
        assert result["cache_entries"] == 1000
        assert result["questions"] == 50000
        assert result["uptime_seconds"] == 3600
        assert result["answers_0_1"] == 100
        assert result["answers_1_10"] == 200

    def test_returns_empty_on_http_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        with patch("agent.requests.get", return_value=mock_response):
            result = scrape_recursor_metrics("http://localhost:8082")
        assert result == {}

    def test_returns_empty_on_exception(self):
        with patch("agent.requests.get", side_effect=Exception("Connection refused")):
            result = scrape_recursor_metrics("http://localhost:8082")
        assert result == {}

    def test_handles_float_values(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "pdns_recursor_cache_hits 123.0\n"
        with patch("agent.requests.get", return_value=mock_response):
            result = scrape_recursor_metrics("http://localhost:8082")
        assert result["cache_hits"] == 123


class TestSyncConfig:
    def test_writes_rpz_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rpz_dir = Path(tmpdir) / "rpz"
            fzones_path = Path(tmpdir) / "forward-zones.conf"

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "rpz_files": [
                    {
                        "filename": "blocklist.rpz",
                        "content": "$ORIGIN blocklist.rpz.\n",
                    },
                    {
                        "filename": "whitelist.rpz",
                        "content": "$ORIGIN whitelist.rpz.\n",
                    },
                ],
                "forward_zones": [],
            }

            with patch("agent.requests.get", return_value=mock_response):
                result = sync_config(
                    "http://primary:8080",
                    {"X-PowerBlockade-Node-Key": "key"},
                    rpz_dir,
                    fzones_path,
                )

            assert result is True
            assert (rpz_dir / "blocklist.rpz").read_text() == "$ORIGIN blocklist.rpz.\n"
            assert (rpz_dir / "whitelist.rpz").read_text() == "$ORIGIN whitelist.rpz.\n"

    def test_writes_forward_zones(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rpz_dir = Path(tmpdir) / "rpz"
            fzones_path = Path(tmpdir) / "forward-zones.conf"

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "rpz_files": [],
                "forward_zones": [
                    {"domain": "internal.lan", "servers": "192.168.1.1"},
                    {"domain": "corp.local", "servers": "10.0.0.1;10.0.0.2"},
                ],
            }

            with patch("agent.requests.get", return_value=mock_response):
                result = sync_config(
                    "http://primary:8080",
                    {"X-PowerBlockade-Node-Key": "key"},
                    rpz_dir,
                    fzones_path,
                )

            assert result is True
            content = fzones_path.read_text()
            assert "internal.lan=192.168.1.1" in content
            assert "corp.local=10.0.0.1;10.0.0.2" in content

    def test_returns_false_on_http_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_response = MagicMock()
            mock_response.status_code = 401

            with patch("agent.requests.get", return_value=mock_response):
                result = sync_config(
                    "http://primary:8080",
                    {"X-PowerBlockade-Node-Key": "bad-key"},
                    Path(tmpdir) / "rpz",
                    Path(tmpdir) / "fz.conf",
                )

            assert result is False

    def test_returns_false_on_exception(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("agent.requests.get", side_effect=Exception("Network error")):
                result = sync_config(
                    "http://primary:8080",
                    {},
                    Path(tmpdir) / "rpz",
                    Path(tmpdir) / "fz.conf",
                )
            assert result is False

    def test_returns_false_when_no_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rpz_dir = Path(tmpdir) / "rpz"
            rpz_dir.mkdir()
            (rpz_dir / "blocklist.rpz").write_text("existing content")
            fzones_path = Path(tmpdir) / "forward-zones.conf"

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "rpz_files": [
                    {"filename": "blocklist.rpz", "content": "existing content"}
                ],
                "forward_zones": [],
            }

            with patch("agent.requests.get", return_value=mock_response):
                result = sync_config(
                    "http://primary:8080",
                    {},
                    rpz_dir,
                    fzones_path,
                )

            assert result is False


class TestGetLocalIp:
    def test_returns_ip_string_for_valid_host(self):
        result = get_local_ip("8.8.8.8")
        if result is not None:
            assert isinstance(result, str)
            parts = result.split(".")
            assert len(parts) == 4

    def test_returns_none_for_invalid_host(self):
        result = get_local_ip("invalid.nonexistent.host.example")
        assert result is None or isinstance(result, str)


class TestGetVersion:
    def test_returns_env_var_when_set(self):
        os.environ["PB_VERSION"] = "1.2.3"
        try:
            assert get_version() == "1.2.3"
        finally:
            del os.environ["PB_VERSION"]

    def test_returns_unknown_when_not_set(self):
        if "PB_VERSION" in os.environ:
            del os.environ["PB_VERSION"]
        assert get_version() == "unknown"
