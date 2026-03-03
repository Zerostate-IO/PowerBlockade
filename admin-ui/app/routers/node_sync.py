from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.models.blocklist import Blocklist
from app.models.client import Client
from app.models.dns_query_event import DNSQueryEvent
from app.models.forward_zone import ForwardZone
from app.models.node import Node, NodeStatus
from app.models.node_metrics import NodeMetrics
from app.models.settings import get_setting, get_health_quarantine_threshold_minutes
from app.settings import get_settings

log = logging.getLogger(__name__)


def get_node_from_api_key(
    x_powerblockade_node_key: str | None = Header(default=None, alias="X-PowerBlockade-Node-Key"),
    db: Session = Depends(get_db),
) -> Node:
    if not x_powerblockade_node_key:
        raise HTTPException(status_code=401, detail="Missing node API key")

    node = db.query(Node).filter(Node.api_key == x_powerblockade_node_key).one_or_none()
    if not node:
        raise HTTPException(status_code=401, detail="Invalid node API key")
    return node


router = APIRouter(prefix="/api/node-sync", tags=["node-sync"])


def compute_config_version() -> str:
    """Compute hash of current RPZ files to detect config changes."""
    import hashlib
    import os

    rpz_dir = "/shared/rpz"
    checksums = []

    for filename in ["blocklist-combined.rpz", "whitelist.rpz"]:
        filepath = os.path.join(rpz_dir, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, "rb") as f:
                    checksums.append(hashlib.sha256(f.read()).hexdigest()[:16])
            except Exception:
                pass

    return hashlib.sha256(":".join(checksums).encode()).hexdigest()[:12]


def check_version_compatibility(primary: str | None, secondary: str | None) -> tuple[str, str]:
    """
    Check version compatibility between primary and secondary nodes.

    Returns (status, message) where status is ALLOW, WARN, or BLOCK.
    - BLOCK: Major version mismatch - config sync forbidden
    - WARN: Minor/patch skew - proceed with warning
    - ALLOW: Compatible versions
    """
    # Handle unknown versions
    if not primary or primary == "unknown":
        if not secondary or secondary == "unknown":
            return ("ALLOW", "Both versions unknown, assuming compatibility")
        return ("WARN", f"Primary version unknown, cannot verify secondary {secondary}")
    if not secondary or secondary == "unknown":
        return ("WARN", f"Secondary version unknown, cannot verify against primary {primary}")

    # Strip 'v' prefix if present
    primary = primary.lstrip("v")
    secondary = secondary.lstrip("v")

    # Parse versions
    try:
        p_parts = list(map(int, primary.split(".")[:3]))
        s_parts = list(map(int, secondary.split(".")[:3]))
        # Pad to 3 parts if needed
        while len(p_parts) < 3:
            p_parts.append(0)
        while len(s_parts) < 3:
            s_parts.append(0)
    except ValueError:
        return ("WARN", f"Unparseable version: primary={primary}, secondary={secondary}")

    p_major, p_minor, p_patch = p_parts
    s_major, s_minor, s_patch = s_parts

    # Major version mismatch = BLOCK
    if p_major != s_major:
        return ("BLOCK", f"Major version mismatch: primary={primary}, secondary={secondary}")

    # Minor version mismatch = WARN
    if p_minor != s_minor:
        return ("WARN", f"Minor version skew: primary={primary}, secondary={secondary}")

    # Patch version behind = WARN
    if s_patch < p_patch:
        return ("WARN", f"Secondary patch behind: primary={primary}, secondary={secondary}")

    return ("ALLOW", f"Versions compatible: primary={primary}, secondary={secondary}")

class RegisterRequest(BaseModel):
    name: str
    version: str | None = None
    ip_address: str | None = None


class HeartbeatRequest(BaseModel):
    queries_total: int | None = None
    queries_blocked: int | None = None
    version: str | None = None


@router.post("/register")
def register(
    payload: RegisterRequest,
    node: Node = Depends(get_node_from_api_key),
    db: Session = Depends(get_db),
):
    # Bind name/ip/version to the API key.
    node.name = payload.name
    node.ip_address = payload.ip_address
    node.version = payload.version
    node.status = "active"
    node.last_seen = datetime.now(timezone.utc)
    node.last_error = None
    db.add(node)
    db.commit()

    return {"ok": True, "config_version": node.config_version}


@router.post("/heartbeat")
def heartbeat(
    payload: HeartbeatRequest,
    node: Node = Depends(get_node_from_api_key),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    previous_status = node.status
    previous_last_seen = node.last_seen  # Save before updating
    node.last_seen = now
    node.last_heartbeat = now

    # Don't auto-clear ERROR or QUARANTINE status - these require manual intervention
    if previous_status in (NodeStatus.ERROR.value, NodeStatus.QUARANTINE.value):
        # Keep existing status, just update heartbeat time
        pass
    elif previous_status == NodeStatus.OFFLINE.value or previous_status == NodeStatus.STALE.value:
        # Check if node was offline long enough to require quarantine
        if previous_last_seen:
            quarantine_threshold = get_health_quarantine_threshold_minutes(db)
            # Cast to datetime since model uses object | None for last_seen
            last_seen_dt = previous_last_seen if isinstance(previous_last_seen, datetime) else None
            if last_seen_dt:
                offline_duration = now - last_seen_dt
                if offline_duration > timedelta(minutes=quarantine_threshold):
                    node.status = NodeStatus.QUARANTINE.value
                    node.quarantine_entry_time = now
                    node.quarantine_reason = f"Returned after {int(offline_duration.total_seconds() / 3600)} hours offline"
                    log.warning(f"Node {node.name} quarantined: returned after {offline_duration}")
                else:
                    node.status = NodeStatus.ACTIVE.value
            else:
                node.status = NodeStatus.ACTIVE.value
        else:
            node.status = NodeStatus.ACTIVE.value
    else:
        node.status = NodeStatus.ACTIVE.value

    if payload.version:
        node.version = payload.version
    if payload.queries_total is not None:
        node.queries_total = payload.queries_total
    if payload.queries_blocked is not None:
        node.queries_blocked = payload.queries_blocked
    db.add(node)
    db.commit()

    current_config_version = compute_config_version()
    return {"ok": True, "config_version": current_config_version}


@router.get("/config")
def config(
    node: Node = Depends(get_node_from_api_key),
    db: Session = Depends(get_db),
):
    """Return configuration bundle for secondary nodes: RPZ files, forward zones, settings."""
    import hashlib
    import json
    import os

    # Version compatibility check
    settings_obj = get_settings()
    primary_version = settings_obj.pb_version
    secondary_version = node.version
    status, message = check_version_compatibility(primary_version, secondary_version)

    if status == "BLOCK":
        log.error(f"Config sync blocked for node {node.name}: {message}")
        raise HTTPException(status_code=409, detail=message)
    elif status == "WARN":
        log.warning(f"Config sync warning for node {node.name}: {message}")

    rpz_files = []
    rpz_dir = "/shared/rpz"

    for filename in ["blocklist-combined.rpz", "whitelist.rpz"]:
        filepath = os.path.join(rpz_dir, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                rpz_files.append(
                    {
                        "filename": filename,
                        "content": content,
                        "checksum": hashlib.sha256(content.encode()).hexdigest()[:16],
                    }
                )
            except Exception as e:
                log.warning(f"Failed to read RPZ file {filename}: {e}")

    global_zones = (
        db.query(ForwardZone)
        .filter(ForwardZone.enabled.is_(True), ForwardZone.node_id.is_(None))
        .all()
    )
    node_zones = (
        db.query(ForwardZone)
        .filter(ForwardZone.enabled.is_(True), ForwardZone.node_id == node.id)
        .all()
    )

    zone_map = {z.domain: z for z in global_zones}
    for z in node_zones:
        zone_map[z.domain] = z

    forward_zones = [
        {
            "domain": z.domain,
            "servers": z.servers,
            "description": z.description,
            "is_override": z.node_id is not None,
        }
        for z in zone_map.values()
    ]

    settings = {
        "retention_events_days": get_setting(db, "retention_events_days"),
        "ptr_resolution_enabled": get_setting(db, "ptr_resolution_enabled"),
        "precache_enabled": get_setting(db, "precache_enabled"),
        "precache_domain_count": get_setting(db, "precache_domain_count"),
        "precache_refresh_minutes": get_setting(db, "precache_refresh_minutes"),
        "precache_ignore_ttl": get_setting(db, "precache_ignore_ttl"),
        "precache_custom_refresh_minutes": get_setting(db, "precache_custom_refresh_minutes"),
    }

    blocklists = db.query(Blocklist).filter(Blocklist.enabled.is_(True)).all()
    blocklist_info = []
    for b in blocklists:
        last_upd_val = b.last_updated
        last_upd_str = last_upd_val.isoformat() if isinstance(last_upd_val, datetime) else None
        blocklist_info.append(
            {
                "name": b.name,
                "list_type": b.list_type,
                "entry_count": b.entry_count,
                "last_updated": last_upd_str,
            }
        )

    config_data = json.dumps(
        {
            "rpz_checksums": [r["checksum"] for r in rpz_files],
            "forward_zones": sorted([f"{z['domain']}={z['servers']}" for z in forward_zones]),
        },
        sort_keys=True,
    )
    computed_version = hashlib.sha256(config_data.encode()).hexdigest()[:12]

    return {
        "ok": True,
        "config_version": computed_version,
        "rpz_files": rpz_files,
        "forward_zones": forward_zones,
        "settings": settings,
        "blocklists": blocklist_info,
    }


@router.get("/precache-domains")
def precache_domains(
    limit: int = 1000,
    node: Node = Depends(get_node_from_api_key),
    db: Session = Depends(get_db),
):
    """Return top domains for secondary nodes to pre-warm their cache."""
    from app.services.precache import get_top_domains_to_warm

    domains = get_top_domains_to_warm(db, hours=24, limit=limit)
    return {
        "ok": True,
        "domains": domains,
        "count": len(domains),
    }


class IngestRequest(BaseModel):
    events: list[dict[str, Any]]


class IngestEvent(BaseModel):
    ts: str | None = None
    client_ip: str
    qname: str
    qtype: int
    rcode: int
    blocked: bool = False
    block_reason: str | None = None
    blocklist_name: str | None = None
    latency_ms: int | None = None
    event_id: str | None = None
    event_seq: int | None = None


def _background_resolve_clients(ips: list[str]) -> None:
    try:
        from app.services.ptr_resolver import resolve_client_hostname

        db = SessionLocal()
        try:
            for ip in ips:
                try:
                    resolve_client_hostname(db, ip)
                except Exception as e:
                    log.debug(f"PTR resolution failed for {ip}: {e}")
        finally:
            db.close()
    except Exception as e:
        log.warning(f"Background PTR resolution error: {e}")


@router.post("/ingest")
def ingest(
    payload: IngestRequest,
    background_tasks: BackgroundTasks,
    node: Node = Depends(get_node_from_api_key),
    db: Session = Depends(get_db),
):
    parsed: list[IngestEvent] = []
    for e in payload.events:
        try:
            parsed.append(IngestEvent.model_validate(e))
        except Exception:
            continue

    if not parsed:
        return {"ok": True, "received": 0, "node": node.name}

    unique_ips = {ev.client_ip for ev in parsed}
    existing = {
        c.ip: c
        for c in db.execute(select(Client).where(Client.ip.in_(list(unique_ips)))).scalars().all()
    }
    for ip in unique_ips:
        if ip not in existing:
            c = Client(ip=ip)
            db.add(c)
            existing[ip] = c
    db.flush()

    from datetime import datetime, timezone

    rows_data = []
    for ev in parsed:
        ts = None
        if ev.ts:
            try:
                ts = datetime.fromisoformat(ev.ts.replace("Z", "+00:00"))
            except Exception:
                ts = None
        if ts is None:
            ts = datetime.now(timezone.utc)

        client = existing[ev.client_ip]
        client.last_seen = ts

        rows_data.append(
            {
                "event_id": ev.event_id,
                "event_seq": ev.event_seq,
                "ts": ts,
                "node_id": node.id,
                "client_ip": ev.client_ip,
                "client_id": client.id,
                "qname": ev.qname.strip().lower().rstrip("."),
                "qtype": ev.qtype,
                "rcode": ev.rcode,
                "blocked": ev.blocked,
                "block_reason": ev.block_reason,
                "blocklist_name": ev.blocklist_name,
                "latency_ms": ev.latency_ms,
            }
        )

    if rows_data:
        log.info(f"Ingest: node={node.name} (id={node.id}) events={len(rows_data)}")
        stmt = pg_insert(DNSQueryEvent).values(rows_data)
        stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
        result = cast(CursorResult, db.execute(stmt))
        inserted = result.rowcount or 0
        if inserted < len(rows_data):
            log.debug(f"Ingest: {len(rows_data) - inserted} duplicates skipped (event_id conflict)")
    else:
        inserted = 0

    node.last_seen = datetime.now(timezone.utc)
    node.status = "active"
    db.add(node)
    db.commit()

    new_ips = [
        ip for ip in unique_ips if ip not in existing or not existing[ip].rdns_last_resolved_at
    ]
    if new_ips:
        background_tasks.add_task(_background_resolve_clients, new_ips)

    return {"ok": True, "received": inserted, "node": node.name}


class MetricsRequest(BaseModel):
    cache_hits: int = 0
    cache_misses: int = 0
    cache_entries: int = 0
    packetcache_hits: int = 0
    packetcache_misses: int = 0
    answers_0_1: int = 0
    answers_1_10: int = 0
    answers_10_100: int = 0
    answers_100_1000: int = 0
    answers_slow: int = 0
    concurrent_queries: int = 0
    outgoing_timeouts: int = 0
    servfail_answers: int = 0
    nxdomain_answers: int = 0
    questions: int = 0
    all_outqueries: int = 0
    uptime_seconds: int = 0


@router.post("/metrics")
def metrics(
    payload: MetricsRequest,
    node: Node = Depends(get_node_from_api_key),
    db: Session = Depends(get_db),
):
    node.last_seen = datetime.now(timezone.utc)
    node.status = "active"
    db.add(node)

    metric = NodeMetrics(
        node_id=node.id,
        cache_hits=payload.cache_hits,
        cache_misses=payload.cache_misses,
        cache_entries=payload.cache_entries,
        packetcache_hits=payload.packetcache_hits,
        packetcache_misses=payload.packetcache_misses,
        answers_0_1=payload.answers_0_1,
        answers_1_10=payload.answers_1_10,
        answers_10_100=payload.answers_10_100,
        answers_100_1000=payload.answers_100_1000,
        answers_slow=payload.answers_slow,
        concurrent_queries=payload.concurrent_queries,
        outgoing_timeouts=payload.outgoing_timeouts,
        servfail_answers=payload.servfail_answers,
        nxdomain_answers=payload.nxdomain_answers,
        questions=payload.questions,
        all_outqueries=payload.all_outqueries,
        uptime_seconds=payload.uptime_seconds,
    )
    db.add(metric)
    db.commit()

    return {"ok": True, "node": node.name}


@router.get("/commands")
def get_commands(
    node: Node = Depends(get_node_from_api_key),
    db: Session = Depends(get_db),
):
    """Get pending commands for this node."""
    from app.models.node_command import NodeCommand

    pending = (
        db.query(NodeCommand)
        .filter(
            NodeCommand.executed_at.is_(None),
            (NodeCommand.node_id == node.id) | (NodeCommand.node_id.is_(None)),
        )
        .order_by(NodeCommand.created_at)
        .all()
    )

    commands = [
        {
            "id": cmd.id,
            "command": cmd.command,
            "params": cmd.params,
            "created_at": cmd.created_at.isoformat() if cmd.created_at else None,
        }
        for cmd in pending
    ]

    return {"ok": True, "commands": commands}


class CommandResultRequest(BaseModel):
    command_id: int
    success: bool
    result: str | None = None


@router.post("/commands/result")
def report_command_result(
    payload: CommandResultRequest,
    node: Node = Depends(get_node_from_api_key),
    db: Session = Depends(get_db),
):
    """Report the result of executing a command."""
    from app.models.node_command import NodeCommand

    cmd = db.query(NodeCommand).filter(NodeCommand.id == payload.command_id).first()
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")

    if cmd.node_id is not None and cmd.node_id != node.id:
        raise HTTPException(status_code=403, detail="Command not for this node")

    cmd.executed_at = datetime.now(timezone.utc)
    cmd.result = f"node={node.name} success={payload.success} result={payload.result}"
    db.commit()

    return {"ok": True}
