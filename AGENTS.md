# PowerBlockade Knowledge Base

**Generated:** 2026-01-28
**Status:** Early scaffolding (MVP in progress)

## Overview

Pi-hole alternative: PowerDNS Recursor + dnstap logging + FastAPI admin UI + Postgres. Modern dark UI, multi-node support, Docker-first.

## Structure

```
powerblockade/
├── admin-ui/           # FastAPI + Jinja2 + SQLAlchemy (main UI, 1600 LOC)
├── dnstap-processor/   # Go service: dnstap → Admin API → Postgres (540 LOC)
├── recursor/           # PowerDNS Recursor config + RPZ zones
├── dnsdist/            # Edge DNS proxy (client IP attribution)
├── sync-agent/         # Secondary node heartbeat (NOT in compose yet)
├── opensearch/         # Index templates (DEFERRED - not MVP)
├── grafana/            # Dashboard provisioning
├── prometheus/         # Metrics scraping
├── docs/               # DESIGN.md, networking notes
└── scripts/            # init-env.sh
```

## Where to Look

| Task | Location | Notes |
|------|----------|-------|
| Add UI page | `admin-ui/app/main.py` | Modular routers (auth, analytics, blocklists, nodes, forward_zones, precache, metrics, help) |
| Add template | `admin-ui/app/templates/` | Jinja2, extends `base.html` |
| Add DB model | `admin-ui/app/models/` | SQLAlchemy 2.0 mapped_column style |
| Add migration | `admin-ui/alembic/versions/` | `alembic revision --autogenerate` |
| Modify DNS logging | `dnstap-processor/cmd/.../main.go` | Go, ships to `/api/node-sync/ingest` |
| Change RPZ behavior | `recursor/rpz.lua` | Lua policy config |
| Add blocklist parser | `admin-ui/app/services/rpz.py` | hosts/domains/adblock formats |
| Node sync API | `admin-ui/app/routers/node_sync.py` | register/heartbeat/ingest endpoints |
| Add forward zone | `admin-ui/app/routers/forward_zones.py` | global + per-node DNS overrides |
| Add help content | `admin-ui/app/routers/help.py` | Contextual help pages ("what-is-this") |

## Data Flow

```
Client → dnsdist:53 → Recursor:5300 → Response
              ↓ dnstap (CLIENT_RESPONSE only)
        dnstap-processor
              ↓ POST /api/node-sync/ingest
        admin-ui → Postgres (dns_query_events)
```

## Conventions

### Python (admin-ui)
- **Tooling**: `uv` for deps, `ruff` for lint (line-length=100)
- **Python**: ≥3.12 required
- **ORM**: SQLAlchemy 2.0 with `Mapped[]` type hints
- **Auth**: Session-based, bcrypt with SHA256 pre-hash (72-byte limit fix)

### Go (dnstap-processor)
- **Version**: go 1.23
- **Structure**: `cmd/` entry, `internal/config/`
- **Deps**: miekg/dns, dnstap, powerdns-protobuf

### Databases
- **Postgres** runs via postgres:16 image
- Connection via `DATABASE_URL`
- SQLAlchemy 2.0 with async Session

### Docker
- **Network**: `172.30.0.0/16` bridge, static IPs for recursor/dnstap-processor
- **Shared volumes**: `dnstap-socket`, `recursor-control-socket`
- **RPZ sharing**: bind-mount `./recursor/rpz` to admin-ui + dnstap-processor

## Anti-Patterns (DO NOT)

| Pattern | Why |
|---------|-----|
| Commit `.env` | Contains secrets |
| Use macvlan on WiFi | Broken; use ipvlan L2 or wired |
| Enable Recursor dnstap when using dnsdist | Causes duplicates |
| Complex `command:` in compose | Gets truncated; use entrypoint scripts |
| `pip install --break-system-packages` | Use pipx or venv |
| Passwords > 72 chars without pre-hash | Bcrypt silently truncates |
| `dnsdist newServer()` with hostname | Must use IP literal (e.g., `172.30.0.10:5300`) |

## Commands

```bash
# Setup
./scripts/init-env.sh          # Generate .env with random secrets
docker compose up -d --build   # Start full stack

# Development
cd admin-ui && uv sync         # Install Python deps
alembic upgrade head           # Run migrations
uvicorn app.main:app --reload  # Dev server

# Apply blocklist changes
# UI: /blocklists → Apply button
# Writes to /shared/rpz/, recursor-reloader picks up in ~5s

# Go service
cd dnstap-processor && go build ./cmd/dnstap-processor
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ADMIN_SECRET_KEY` | Session signing | required |
| `ADMIN_PASSWORD` | Bootstrap admin user | required |
| `DATABASE_URL` | Postgres DSN | `postgresql+psycopg://...` |
| `RECURSOR_API_KEY` | Recursor webserver auth | required |
| `PRIMARY_API_KEY` | Node auth for dnstap-processor | required for logging |

## Architecture Decisions

- **Postgres-first**: No OpenSearch for MVP (rPi-friendly)
- **Response-only logging**: dnstap CLIENT_RESPONSE only (Pi-hole style)
- **Edge attribution**: dnsdist captures true client IP, not recursor internal
- **Polling reload**: recursor-reloader runs `rec_control` every 5s (not signal-based)

## Known Issues / Tech Debt

1. `sync-agent` has Dockerfile but missing from docker-compose.yml
2. No test suite yet (pytest configured but no tests)
3. In-container migrations can race in scaled deployments
4. Containers run as root (USER 0:0)
5. Forward zones config writes to `/shared/forward-zones.conf` but recursor-reloader doesn't reload it yet
6. Precache uses 5ms threshold for cache hit - may need tuning based on real data

## Hierarchy

```
./AGENTS.md (this file)
└── admin-ui/AGENTS.md
```
