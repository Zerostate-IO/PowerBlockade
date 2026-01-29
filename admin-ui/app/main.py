from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.routers.analytics import router as analytics_router
from app.routers.audit import router as audit_router
from app.routers.auth import router as auth_router
from app.routers.blocklists import router as blocklists_router
from app.routers.client_resolver import router as client_resolver_router
from app.routers.forward_zones import router as forward_zones_router
from app.routers.grafana_proxy import router as grafana_proxy_router
from app.routers.help import router as help_router
from app.routers.jobs import router as jobs_router
from app.routers.metrics import router as metrics_router
from app.routers.node_sync import router as node_sync_router
from app.routers.nodes import router as nodes_router
from app.routers.precache import router as precache_router
from app.routers.system import router as system_router
from app.security import hash_password
from app.settings import get_settings

settings = get_settings()


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
    from sqlalchemy import text

    from app.db.session import engine

    if not settings.primary_api_key:
        return

    with engine.begin() as conn:
        try:
            conn.execute(text("SELECT 1 FROM nodes LIMIT 1"))
        except Exception:
            return

        existing = conn.execute(
            text("SELECT id FROM nodes WHERE name = 'primary' OR api_key = :k"),
            {"k": settings.primary_api_key},
        ).fetchone()
        if existing is None:
            conn.execute(
                text("INSERT INTO nodes (name, api_key, status) VALUES (:n, :k, 'active')"),
                {"n": "primary", "k": settings.primary_api_key},
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.services.scheduler import start_scheduler, stop_scheduler

    bootstrap_admin()
    bootstrap_primary_node()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="PowerBlockade Admin UI", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.admin_secret_key)

app.include_router(node_sync_router)
app.include_router(auth_router)
app.include_router(analytics_router)
app.include_router(blocklists_router)
app.include_router(nodes_router)
app.include_router(forward_zones_router)
app.include_router(precache_router)
app.include_router(metrics_router)
app.include_router(help_router)
app.include_router(client_resolver_router)
app.include_router(jobs_router)
app.include_router(audit_router)
app.include_router(system_router)
app.include_router(grafana_proxy_router)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/version")
def version():
    return {
        "version": settings.pb_version,
        "git_sha": settings.pb_git_sha,
        "build_date": settings.pb_build_date,
        "api_protocol_version": settings.node_protocol_version,
        "api_protocol_min_supported": settings.node_protocol_min_supported,
    }
