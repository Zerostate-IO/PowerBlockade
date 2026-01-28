"""Unit tests for forward zones config generation service."""

from unittest.mock import MagicMock

from app.services.forward_zones import generate_forward_zones_config


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
