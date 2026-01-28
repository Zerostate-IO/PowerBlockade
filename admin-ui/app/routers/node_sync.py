from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.models.client import Client
from app.models.dns_query_event import DNSQueryEvent
from app.models.node import Node

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
    node.last_seen = datetime.now(timezone.utc)
    node.status = "active"
    if payload.version:
        node.version = payload.version
    if payload.queries_total is not None:
        node.queries_total = payload.queries_total
    if payload.queries_blocked is not None:
        node.queries_blocked = payload.queries_blocked
    db.add(node)
    db.commit()

    return {"ok": True, "config_version": node.config_version}


@router.get("/config")
def config(
    node: Node = Depends(get_node_from_api_key),
):
    # Placeholder until we implement real config versioning + downloads.
    return {
        "ok": True,
        "config_version": node.config_version,
        "rpz_files": [],
        "forward_zones": [],
        "settings": {},
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
        stmt = pg_insert(DNSQueryEvent).values(rows_data)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_node_event_seq")
        result = cast(CursorResult, db.execute(stmt))
        inserted = result.rowcount or 0
    else:
        inserted = 0

    db.commit()

    new_ips = [
        ip for ip in unique_ips if ip not in existing or not existing[ip].rdns_last_resolved_at
    ]
    if new_ips:
        background_tasks.add_task(_background_resolve_clients, new_ips)

    return {"ok": True, "received": inserted, "node": node.name}
