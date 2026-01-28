from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.session import get_db
from app.models.node import Node
from app.models.client import Client
from app.models.dns_query_event import DNSQueryEvent


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


@router.post("/ingest")
def ingest(
    payload: IngestRequest,
    node: Node = Depends(get_node_from_api_key),
    db: Session = Depends(get_db),
):
    # Accept a batch of events from a node and store into Postgres.
    parsed: list[IngestEvent] = []
    for e in payload.events:
        try:
            parsed.append(IngestEvent.model_validate(e))
        except Exception:
            continue

    if not parsed:
        return {"ok": True, "received": 0, "node": node.name}

    # Upsert clients (by IP)
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

    rows: list[DNSQueryEvent] = []
    from datetime import datetime, timezone

    for ev in parsed:
        # ts parsing: accept RFC3339-ish string; fallback to now.
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

        rows.append(
            DNSQueryEvent(
                event_id=ev.event_id,
                ts=ts,
                node_id=node.id,
                client_ip=ev.client_ip,
                client_id=client.id,
                qname=ev.qname.strip().lower().rstrip("."),
                qtype=ev.qtype,
                rcode=ev.rcode,
                blocked=ev.blocked,
                block_reason=ev.block_reason,
                blocklist_name=ev.blocklist_name,
                latency_ms=ev.latency_ms,
            )
        )

    db.add_all(rows)
    db.commit()

    return {"ok": True, "received": len(rows), "node": node.name}
