"""Unit tests for forward zones config generation service."""

import os
from unittest.mock import MagicMock, patch

from app.services.forward_zones import generate_forward_zones_config, write_forward_zones_config


class TestGenerateForwardZonesConfig:
    def test_generate_empty_config(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        config = generate_forward_zones_config(mock_db)

        assert "Forward zones" in config
        assert "Generated automatically" in config

    def test_generate_single_zone(self):
        mock_zone = MagicMock()
        mock_zone.domain = "internal.corp.local"
        mock_zone.servers = "10.0.1.53"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_zone]

        config = generate_forward_zones_config(mock_db)

        assert "internal.corp.local=10.0.1.53" in config

    def test_generate_multiple_zones(self):
        mock_zone1 = MagicMock()
        mock_zone1.domain = "corp.local"
        mock_zone1.servers = "10.0.1.53"

        mock_zone2 = MagicMock()
        mock_zone2.domain = "dev.local"
        mock_zone2.servers = "127.0.0.1:5353"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_zone1, mock_zone2]

        config = generate_forward_zones_config(mock_db)

        assert "corp.local=10.0.1.53" in config
        assert "dev.local=127.0.0.1:5353" in config

    def test_generate_with_multiple_servers(self):
        mock_zone = MagicMock()
        mock_zone.domain = "corp.local"
        mock_zone.servers = "10.0.1.53,10.0.1.54,10.0.1.55"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_zone]

        config = generate_forward_zones_config(mock_db)

        assert "corp.local=10.0.1.53,10.0.1.54,10.0.1.55" in config

    def test_only_queries_enabled_global_zones(self):
        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.all.return_value = []

        generate_forward_zones_config(mock_db)

        mock_query.filter.assert_called_once()


class TestWriteForwardZonesConfig:
    def test_returns_generated_content(self, tmp_path):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        out_file = tmp_path / "forward-zones.conf"
        content = write_forward_zones_config(mock_db, out_path=str(out_file))

        assert "Forward zones" in content
        assert out_file.exists()

    def test_writes_file_content(self, tmp_path):
        mock_zone = MagicMock()
        mock_zone.domain = "corp.local"
        mock_zone.servers = "10.0.1.53"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_zone]

        out_file = tmp_path / "forward-zones.conf"
        write_forward_zones_config(mock_db, out_path=str(out_file))

        content = out_file.read_text()
        assert "corp.local=10.0.1.53" in content

    def test_preserves_inode_on_overwrite(self, tmp_path):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        out_file = tmp_path / "forward-zones.conf"

        write_forward_zones_config(mock_db, out_path=str(out_file))
        inode_before = out_file.stat().st_ino

        write_forward_zones_config(mock_db, out_path=str(out_file))
        inode_after = out_file.stat().st_ino

        assert inode_before == inode_after

    def test_no_temp_files_left_behind(self, tmp_path):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        out_file = tmp_path / "forward-zones.conf"

        write_forward_zones_config(mock_db, out_path=str(out_file))

        temp_files = [f for f in os.listdir(tmp_path) if f.startswith(".pb-tmp-")]
        assert temp_files == []

    def test_creates_parent_directory(self, tmp_path):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        nested_dir = tmp_path / "nested" / "dir"
        out_file = nested_dir / "forward-zones.conf"

        write_forward_zones_config(mock_db, out_path=str(out_file))

        assert out_file.exists()
        assert "Forward zones" in out_file.read_text()

    def test_delegates_to_safe_write(self, tmp_path):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        out_file = tmp_path / "forward-zones.conf"

        with patch("app.services.forward_zones.safe_write") as mock_sw:
            write_forward_zones_config(mock_db, out_path=str(out_file))
            mock_sw.assert_called_once()
            assert mock_sw.call_args[0][0] == str(out_file)
            assert "Forward zones" in mock_sw.call_args[0][1]

    def test_write_completes_successfully(self, tmp_path):
        """Verify write_forward_zones_config returns content after safe_write."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        out_file = tmp_path / "forward-zones.conf"
        content = write_forward_zones_config(mock_db, out_path=str(out_file))

        assert "Forward zones" in content
        assert out_file.exists()
