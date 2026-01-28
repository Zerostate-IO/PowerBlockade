"""mvp core tables (events, blocklists, overrides, client naming)

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-28

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ip", sa.String(length=64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("rdns_name", sa.String(length=255), nullable=True),
        sa.Column("rdns_last_resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rdns_last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "client_name_resolution_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("cidr", sa.String(length=64), nullable=False),
        sa.Column("resolvers", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_table(
        "blocklists",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("format", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "update_frequency_hours", sa.Integer(), server_default=sa.text("24"), nullable=False
        ),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_update_status", sa.String(length=20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("entry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("last_modified", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_table(
        "manual_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("domain", sa.String(length=255), nullable=False, unique=True),
        sa.Column("entry_type", sa.String(length=10), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_table(
        "forward_zones_global",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("domain", sa.String(length=255), nullable=False, unique=True),
        sa.Column("servers", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_table(
        "forward_zones_node",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "node_id", sa.Integer(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("servers", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("node_id", "domain", name="uq_forward_zones_node"),
    )

    op.create_table(
        "config_versions",
        sa.Column("component", sa.String(length=50), primary_key=True),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # Raw events table (partitioning handled later; MVP uses a plain table initially)
    op.create_table(
        "dns_query_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=True, unique=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column(
            "node_id", sa.Integer(), sa.ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("client_ip", sa.String(length=64), nullable=False, index=True),
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("qname", sa.Text(), nullable=False),
        sa.Column("qtype", sa.Integer(), nullable=False),
        sa.Column("rcode", sa.Integer(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("block_reason", sa.String(length=50), nullable=True),
        sa.Column("blocklist_name", sa.String(length=255), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
    )

    op.create_index(
        "ix_dns_query_events_client_ts",
        "dns_query_events",
        ["client_ip", "ts"],
    )


def downgrade() -> None:
    op.drop_index("ix_dns_query_events_client_ts", table_name="dns_query_events")
    op.drop_table("dns_query_events")
    op.drop_table("config_versions")
    op.drop_table("forward_zones_node")
    op.drop_table("forward_zones_global")
    op.drop_table("manual_entries")
    op.drop_table("blocklists")
    op.drop_table("client_name_resolution_rules")
    op.drop_table("clients")
