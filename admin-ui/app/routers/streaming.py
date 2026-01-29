"""WebSocket router for real-time DNS query streaming."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.dns_query_event import DNSQueryEvent
from app.models.user import User

router = APIRouter()
log = logging.getLogger(__name__)

# Track active connections for metrics
_active_connections: set[WebSocket] = set()

# Polling interval in seconds
POLL_INTERVAL = 2.0


def _validate_session(session_token: str) -> int | None:
    """Validate a session token and return user_id if valid.

    The session_token is the user_id that was stored in the session cookie.
    For WebSocket auth, we verify the user still exists in the database.
    """
    try:
        user_id = int(session_token)
    except (ValueError, TypeError):
        return None

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        return user.id if user else None
    finally:
        db.close()


def _fetch_recent_events(last_id: int, limit: int = 50) -> list[dict]:
    """Fetch events newer than last_id from database."""
    db = SessionLocal()
    try:
        stmt = (
            select(DNSQueryEvent)
            .where(DNSQueryEvent.id > last_id)
            .order_by(DNSQueryEvent.id.asc())
            .limit(limit)
        )
        events = db.execute(stmt).scalars().all()
        return [
            {
                "id": e.id,
                "ts": e.ts.isoformat() if e.ts else None,
                "client_ip": e.client_ip,
                "qname": e.qname,
                "qtype": e.qtype,
                "rcode": e.rcode,
                "blocked": e.blocked,
                "latency_ms": e.latency_ms,
            }
            for e in events
        ]
    finally:
        db.close()


def _get_max_event_id() -> int:
    """Get the current maximum event ID."""
    db = SessionLocal()
    try:
        stmt = select(DNSQueryEvent.id).order_by(DNSQueryEvent.id.desc()).limit(1)
        result = db.execute(stmt).scalar()
        return result or 0
    finally:
        db.close()


@router.websocket("/ws/stream")
async def stream_queries(websocket: WebSocket):
    """Stream new DNS query events in real-time to authenticated clients.

    Authentication: Pass user_id as query param (obtained from session cookie on page load).
    Protocol:
    - Connect with ?user_id=<id>
    - Server sends {"type": "connected", "last_id": N}
    - Server polls DB every 2s and sends {"type": "events", "data": [...]}
    - Client can send {"type": "ping"} to keep alive
    - Client can send {"type": "set_last_id", "last_id": N} to rewind/forward
    """
    user_id_param = websocket.query_params.get("user_id")
    if not user_id_param:
        await websocket.close(code=4001, reason="Missing user_id parameter")
        return

    user_id = _validate_session(user_id_param)
    if not user_id:
        await websocket.close(code=4003, reason="Invalid or expired session")
        return

    await websocket.accept()
    _active_connections.add(websocket)
    log.info(f"WebSocket client connected (user_id={user_id}), total: {len(_active_connections)}")

    # Start from current max ID (only stream new events)
    last_id = _get_max_event_id()

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "message": "Streaming active",
                "last_id": last_id,
            }
        )

        while True:
            # Check for incoming messages (non-blocking)
            try:
                # Short timeout to check for client messages
                message = await asyncio.wait_for(websocket.receive_json(), timeout=POLL_INTERVAL)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif message.get("type") == "set_last_id":
                    new_last_id = message.get("last_id")
                    if isinstance(new_last_id, int) and new_last_id >= 0:
                        last_id = new_last_id
                        await websocket.send_json({"type": "last_id_updated", "last_id": last_id})
            except asyncio.TimeoutError:
                # No message received, proceed to poll DB
                pass

            # Poll for new events
            events = await asyncio.to_thread(_fetch_recent_events, last_id)
            if events:
                last_id = events[-1]["id"]
                await websocket.send_json(
                    {
                        "type": "events",
                        "data": events,
                        "count": len(events),
                    }
                )

    except WebSocketDisconnect:
        log.info(f"WebSocket client disconnected (user_id={user_id})")
    except Exception as e:
        log.error(f"WebSocket error (user_id={user_id}): {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        _active_connections.discard(websocket)
        log.info(f"WebSocket cleanup, remaining: {len(_active_connections)}")


def get_connection_count() -> int:
    """Return current number of active WebSocket connections."""
    return len(_active_connections)
