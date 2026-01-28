"""Unit tests for forward zones config generation service."""

import pytest
from pathlib import Path

from app.services.forward_zones import generate_config


class TestGenerateConfig:
    def test_generate_empty_config(self):
        config = generate_config([])
        assert config == ""

    def test_generate_single_global_zone(self):
        zones = [
            {
                "name": "internal.corp.local",
                "nameservers": "10.0.1.53",
                "scope": "global",
            }
        ]
        config = generate_config(zones)
        assert "forward-zone:" in config
        assert "name: internal.corp.local" in config
        assert "forward-addr: 10.0.1.53" in config

    def test_generate_multiple_global_zones(self):
        zones = [
            {"name": "corp.local", "nameservers": "10.0.1.53", "scope": "global"},
            {
                "name": "dev.local",
                "nameservers": "127.0.0.1:5353",
                "scope": "global",
            },
        ]
        config = generate_config(zones)

        assert "forward-zone:" in config
        assert "name: corp.local" in config
        assert "name: dev.local" in config

    def test_generate_with_multiple_nameservers(self):
        zones = [
            {
                "name": "corp.local",
                "nameservers": "10.0.1.53,10.0.1.54,10.0.1.55",
                "scope": "global",
            }
        ]
        config = generate_config(zones)

        assert "forward-addr: 10.0.1.53" in config
        assert "forward-addr: 10.0.1.54" in config
        assert "forward-addr: 10.0.1.55" in config

    def test_filters_per_node_zones_correctly(self, sync_db_session):
        from app.models.node import Node
        from app.models.forward_zone import ForwardZone

        node1 = Node(name="node1", api_key="key1", status="active")
        node2 = Node(name="node2", api_key="key2", status="active")
        sync_db_session.add(node1)
        sync_db_session.add(node2)
        sync_db_session.commit()

        zone1 = ForwardZone(name="global.local", nameservers="10.0.1.1", scope="global")
        zone2 = ForwardZone(name="node1.local", nameservers="10.0.1.2", node=node1)
        zone3 = ForwardZone(name="node2.local", nameservers="10.0.1.3", node=node2)
        sync_db_session.add(zone1)
        sync_db_session.add(zone2)
        sync_db_session.add(zone3)
        sync_db_session.commit()

        from app.services.forward_zones import generate_config_from_db

        config = generate_config_from_db(sync_db_session, node_id=node1.id)

        assert "name: global.local" in config
        assert "name: node1.local" in config
        assert "name: node2.local" not in config

    def test_global_zones_included_for_all_nodes(self, sync_db_session):
        from app.models.node import Node
        from app.models.forward_zone import ForwardZone

        node = Node(name="node1", api_key="key1", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        zone = ForwardZone(name="global.local", nameservers="10.0.1.1")
        sync_db_session.add(zone)
        sync_db_session.commit()

        from app.services.forward_zones import generate_config_from_db

        config = generate_config_from_db(sync_db_session, node_id=node.id)

        assert "name: global.local" in config
        assert "forward-addr: 10.0.1.1" in config
