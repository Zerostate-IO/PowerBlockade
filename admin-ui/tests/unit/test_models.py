"""Unit tests for SQLAlchemy models."""

from datetime import datetime, timezone

from app.models.blocklist import Blocklist
from app.models.client import Client
from app.models.dns_query_event import DNSQueryEvent
from app.models.forward_zone import ForwardZone
from app.models.manual_entry import ManualEntry
from app.models.node import Node
from app.models.user import User


class TestUser:
    def test_user_creation(self, sync_db_session):
        user = User(username="testuser", password_hash="hashed_password")
        sync_db_session.add(user)
        sync_db_session.commit()

        retrieved = sync_db_session.query(User).filter_by(username="testuser").first()
        assert retrieved is not None
        assert retrieved.username == "testuser"


class TestBlocklist:
    def test_blocklist_creation(self, sync_db_session):
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

        retrieved = sync_db_session.query(Blocklist).filter_by(name="Test List").first()
        assert retrieved is not None
        assert retrieved.url == "https://example.com/list.txt"
        assert retrieved.list_type == "block"
        assert retrieved.enabled is True


class TestManualEntry:
    def test_manual_entry_creation(self, sync_db_session):
        entry = ManualEntry(
            id=1,
            domain="malware.example.com",
            entry_type="block",
        )
        sync_db_session.add(entry)
        sync_db_session.commit()

        retrieved = (
            sync_db_session.query(ManualEntry).filter_by(domain="malware.example.com").first()
        )
        assert retrieved is not None
        assert retrieved.entry_type == "block"


class TestForwardZone:
    def test_forward_zone_creation_global(self, sync_db_session):
        zone = ForwardZone(
            id=1,
            domain="internal.corp.local",
            servers="10.0.1.53,10.0.1.54",
            enabled=True,
        )
        sync_db_session.add(zone)
        sync_db_session.commit()

        retrieved = (
            sync_db_session.query(ForwardZone).filter_by(domain="internal.corp.local").first()
        )
        assert retrieved is not None
        assert retrieved.servers == "10.0.1.53,10.0.1.54"
        assert retrieved.node_id is None

    def test_forward_zone_creation_per_node(self, sync_db_session):
        node = Node(id=1, name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        zone = ForwardZone(
            id=1,
            domain="dev.local",
            servers="127.0.0.1:5353",
            node_id=node.id,
        )
        sync_db_session.add(zone)
        sync_db_session.commit()

        retrieved = sync_db_session.query(ForwardZone).filter_by(domain="dev.local").first()
        assert retrieved is not None
        assert retrieved.node_id == node.id


class TestDNSQueryEvent:
    def test_query_event_creation(self, sync_db_session):
        event = DNSQueryEvent(
            id=1,
            ts=datetime.now(timezone.utc),
            client_ip="192.168.1.100",
            qname="example.com",
            qtype=1,
            rcode=0,
            blocked=False,
            latency_ms=3,
        )
        sync_db_session.add(event)
        sync_db_session.commit()

        retrieved = sync_db_session.query(DNSQueryEvent).filter_by(qname="example.com").first()
        assert retrieved is not None
        assert retrieved.client_ip == "192.168.1.100"
        assert retrieved.qtype == 1
        assert retrieved.blocked is False
        assert retrieved.latency_ms == 3

    def test_query_event_with_node(self, sync_db_session):
        node = Node(id=1, name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        event = DNSQueryEvent(
            id=1,
            ts=datetime.now(timezone.utc),
            client_ip="192.168.1.100",
            qname="example.com",
            qtype=1,
            rcode=0,
            blocked=False,
            latency_ms=3,
            node_id=node.id,
        )
        sync_db_session.add(event)
        sync_db_session.commit()

        retrieved = sync_db_session.query(DNSQueryEvent).first()
        assert retrieved is not None
        assert retrieved.node_id == node.id


class TestClient:
    def test_client_creation(self, sync_db_session):
        client = Client(
            id=1,
            ip="192.168.1.100",
            rdns_name="laptop.example.com",
        )
        sync_db_session.add(client)
        sync_db_session.commit()

        retrieved = sync_db_session.query(Client).filter_by(ip="192.168.1.100").first()
        assert retrieved is not None
        assert retrieved.rdns_name == "laptop.example.com"


class TestNode:
    def test_node_creation(self, sync_db_session):
        node = Node(id=1, name="test_node", api_key="test_key", status="active")
        sync_db_session.add(node)
        sync_db_session.commit()

        retrieved = sync_db_session.query(Node).filter_by(name="test_node").first()
        assert retrieved is not None
        assert retrieved.api_key == "test_key"
        assert retrieved.status == "active"
