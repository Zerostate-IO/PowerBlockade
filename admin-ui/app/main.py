from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)

from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.sessions import SessionMiddleware

from app.csrf import CSRFMiddleware
from app.routers.analytics import router as analytics_router
from app.routers.audit import router as audit_router
from app.routers.auth import router as auth_router
from app.routers.backup import router as backup_router
from app.routers.blocking import router as blocking_router
from app.routers.blocklists import router as blocklists_router
from app.routers.client_groups import router as client_groups_router
from app.routers.client_resolver import router as client_resolver_router
from app.routers.entries import router as entries_router
from app.routers.forward_zones import router as forward_zones_router
from app.routers.grafana_proxy import router as grafana_proxy_router
from app.routers.help import router as help_router
from app.routers.jobs import router as jobs_router
from app.routers.metrics import router as metrics_router
from app.routers.metrics_dashboard import router as metrics_dashboard_router
from app.routers.node_sync import router as node_sync_router
from app.routers.nodes import router as nodes_router
from app.routers.precache import router as precache_router
from app.routers.settings import router as settings_router
from app.routers.streaming import router as streaming_router
from app.routers.system import router as system_router
from app.security import hash_password
from app.settings import get_settings

settings = get_settings()
log = logging.getLogger(__name__)

INSECURE_DEFAULTS = {"change-me", "password", "admin", "secret", ""}


def validate_security_settings() -> None:
    """Validate that critical security settings are not using defaults."""
    allow_insecure = os.environ.get("POWERBLOCKADE_ALLOW_INSECURE", "").lower() == "true"

    issues: list[str] = []

    if settings.admin_password in INSECURE_DEFAULTS:
        issues.append("ADMIN_PASSWORD is set to a default/weak value")
    if settings.admin_secret_key in INSECURE_DEFAULTS:
        issues.append("ADMIN_SECRET_KEY is set to a default/weak value")
    if settings.primary_api_key and settings.primary_api_key in INSECURE_DEFAULTS:
        issues.append("PRIMARY_API_KEY is set to a default/weak value")

    if not issues:
        return

    msg = "\n".join(f"  - {issue}" for issue in issues)
    if allow_insecure:
        log.warning(
            f"SECURITY WARNING (bypassed via POWERBLOCKADE_ALLOW_INSECURE):\n{msg}\n"
            "This is UNSAFE for production use!"
        )
    else:
        log.error(
            f"SECURITY ERROR - Cannot start with insecure configuration:\n{msg}\n\n"
            "To fix: Run ./scripts/init-env.sh to generate secure values,\n"
            "or set environment variables with secure random values.\n\n"
            "To bypass (DEVELOPMENT ONLY): Set POWERBLOCKADE_ALLOW_INSECURE=true"
        )
        sys.exit(1)


def bootstrap_admin() -> None:
    # Best-effort bootstrap: ensure admin user exists.
    # Migrations should create the table; if not, skip.
    from sqlalchemy import text

    from app.db.session import engine

    with engine.begin() as conn:
        try:
            conn.execute(text("SELECT 1 FROM users LIMIT 1"))
        except Exception:
            return

        username = settings.admin_username
        password = settings.admin_password
        existing = conn.execute(
            text("SELECT id FROM users WHERE username = :u"),
            {"u": username},
        ).fetchone()
        if existing is None:
            conn.execute(
                text("INSERT INTO users (username, password_hash) VALUES (:u, :p)"),
                {"u": username, "p": hash_password(password)},
            )


def bootstrap_primary_node() -> None:
    import hashlib
    import socket

    from sqlalchemy import text

    from app.db.session import engine

    node_name = settings.node_name or socket.gethostname()
    local_key = settings.local_node_api_key
    if not local_key:
        seed = f"{node_name}:{settings.admin_secret_key}"
        local_key = hashlib.sha256(seed.encode()).hexdigest()

    with engine.begin() as conn:
        try:
            conn.execute(text("SELECT 1 FROM nodes LIMIT 1"))
        except Exception:
            return

        existing = conn.execute(
            text("SELECT id FROM nodes WHERE name = :n"),
            {"n": node_name},
        ).fetchone()
        if existing is None:
            conn.execute(
                text(
                    "INSERT INTO nodes (name, api_key, status, last_seen) "
                    "VALUES (:n, :k, 'active', NOW())"
                ),
                {"n": node_name, "k": local_key},
            )
        else:
            conn.execute(
                text("UPDATE nodes SET last_seen = NOW() WHERE name = :n"),
                {"n": node_name},
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.services.scheduler import start_scheduler, stop_scheduler

    validate_security_settings()
    bootstrap_admin()
    bootstrap_primary_node()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="PowerBlockade Admin UI", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.admin_secret_key,
    same_site="lax",
    https_only=False,
)
app.add_middleware(
    CSRFMiddleware,
    secret_key=settings.admin_secret_key,
    exempt_paths=[
        "/api/",  # API endpoints use their own auth (API keys)
        "/health",  # Health check
        "/metrics",  # Prometheus metrics
        "/grafana/",  # Grafana proxy (has its own auth/CSRF)
    ],
    cookie_secure=False,  # Set True when using HTTPS
    cookie_samesite="lax",
)

app.include_router(node_sync_router)
app.include_router(blocking_router)
app.include_router(auth_router)
app.include_router(analytics_router)
app.include_router(blocklists_router)
app.include_router(entries_router)
app.include_router(forward_zones_router)
app.include_router(nodes_router)
app.include_router(streaming_router)
app.include_router(precache_router)
app.include_router(metrics_router)
app.include_router(help_router)
app.include_router(client_resolver_router)
app.include_router(client_groups_router)
app.include_router(backup_router)
app.include_router(jobs_router)
app.include_router(audit_router)
app.include_router(system_router)
app.include_router(settings_router)
app.include_router(metrics_dashboard_router)
app.include_router(grafana_proxy_router)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/version")
def version(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {
        "version": settings.pb_version,
        "git_sha": settings.pb_git_sha,
        "build_date": settings.pb_build_date,
        "api_protocol_version": settings.node_protocol_version,
        "api_protocol_min_supported": settings.node_protocol_min_supported,
    }
