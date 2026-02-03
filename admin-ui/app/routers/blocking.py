from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.node import Node
from app.models.node_command import NodeCommand
from app.models.settings import get_blocking_state, set_blocking_state
from app.routers.auth import get_current_user
from app.services.config_audit import record_change
from app.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/blocking", tags=["blocking"])


def _write_emergency_rpz() -> None:
    """Write an empty RPZ zone file to effectively disable blocking."""
    out_dir = "/shared/rpz"
    os.makedirs(out_dir, exist_ok=True)

    now = int(time.time())
    empty_zone = (
        f"$TTL 300\n"
        f"@ IN SOA localhost. hostmaster.localhost. {now} 3600 600 604800 300\n"
        f"@ IN NS localhost.\n"
        f"; BLOCKING DISABLED - emergency mode\n"
    )

    with open(os.path.join(out_dir, "blocklist-combined.rpz"), "w", encoding="utf-8") as f:
        f.write(empty_zone)


def _is_blocking_active(db) -> bool:
    """Check if blocking is currently active based on state setting."""
    state = get_blocking_state(db)
    if state == "enabled":
        return True
    if state == "disabled":
        return False

    try:
        pause_until = datetime.fromisoformat(state)
        if pause_until.tzinfo is None:
            pause_until = pause_until.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= pause_until
    except (ValueError, TypeError):
        return True


@router.get("/status")
def blocking_status(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    state = get_blocking_state(db)
    active = _is_blocking_active(db)

    pause_remaining = None
    if state not in ("enabled", "disabled"):
        try:
            pause_until = datetime.fromisoformat(state)
            if pause_until.tzinfo is None:
                pause_until = pause_until.replace(tzinfo=timezone.utc)
            remaining = pause_until - datetime.now(timezone.utc)
            if remaining.total_seconds() > 0:
                pause_remaining = int(remaining.total_seconds())
        except (ValueError, TypeError):
            pass

    return {
        "state": state,
        "active": active,
        "pause_remaining_seconds": pause_remaining,
    }


@router.post("/disable")
def blocking_disable(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    old_state = get_blocking_state(db)
    set_blocking_state(db, "disabled")
    _write_emergency_rpz()

    record_change(
        db,
        entity_type="settings",
        entity_id=0,
        action="blocking_disable",
        actor_user_id=user.id,
        before_data={"blocking_state": old_state},
        after_data={"blocking_state": "disabled"},
    )
    db.commit()

    log.warning(f"Blocking DISABLED by user {user.username}")
    return {"ok": True, "state": "disabled", "message": "Blocking disabled. RPZ zone cleared."}


@router.post("/enable")
def blocking_enable(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    old_state = get_blocking_state(db)
    set_blocking_state(db, "enabled")

    record_change(
        db,
        entity_type="settings",
        entity_id=0,
        action="blocking_enable",
        actor_user_id=user.id,
        before_data={"blocking_state": old_state},
        after_data={"blocking_state": "enabled"},
    )
    db.commit()

    log.info(f"Blocking ENABLED by user {user.username}")
    return {
        "ok": True,
        "state": "enabled",
        "message": "Blocking enabled. Apply blocklists to regenerate RPZ zones.",
    }


@router.post("/pause")
def blocking_pause(request: Request, minutes: int = 15, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if minutes < 1 or minutes > 1440:
        return JSONResponse({"error": "Minutes must be between 1 and 1440"}, status_code=400)

    old_state = get_blocking_state(db)
    pause_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    set_blocking_state(db, pause_until.isoformat())
    _write_emergency_rpz()

    record_change(
        db,
        entity_type="settings",
        entity_id=0,
        action="blocking_pause",
        actor_user_id=user.id,
        before_data={"blocking_state": old_state},
        after_data={"blocking_state": pause_until.isoformat()},
    )
    db.commit()

    log.warning(f"Blocking PAUSED for {minutes} minutes by user {user.username}")
    return {
        "ok": True,
        "state": pause_until.isoformat(),
        "pause_until": pause_until.isoformat(),
        "message": f"Blocking paused for {minutes} minutes.",
    }


@router.post("/clear-cache")
def clear_cache(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    settings = get_settings()
    results = []

    recursor_url = settings.recursor_api_url.rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.delete(
                f"{recursor_url}/api/v1/servers/localhost/cache/flush",
                headers={"X-API-Key": os.environ.get("RECURSOR_API_KEY", "")},
                params={"domain": "."},
            )
            if resp.status_code == 200:
                data = resp.json()
                results.append({"node": "primary", "success": True, "count": data.get("count", 0)})
            else:
                results.append({"node": "primary", "success": False, "error": resp.text})
    except Exception as e:
        results.append({"node": "primary", "success": False, "error": str(e)})

    secondary_nodes = db.query(Node).filter(Node.status == "active").all()
    commands_queued = 0
    for node in secondary_nodes:
        cmd = NodeCommand(node_id=node.id, command="clear_cache")
        db.add(cmd)
        commands_queued += 1

    record_change(
        db,
        entity_type="settings",
        entity_id=0,
        action="cache_clear",
        actor_user_id=user.id,
        after_data={"results": results, "commands_queued": commands_queued},
    )
    db.commit()

    log.info(f"Cache cleared by user {user.username}: {results}, queued {commands_queued} commands")
    return {"ok": True, "results": results, "commands_queued": commands_queued}
