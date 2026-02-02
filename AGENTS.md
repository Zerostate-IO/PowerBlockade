# PowerBlockade Knowledge Base

**Generated:** 2026-02-02
**Version:** 0.3.1
**Status:** MVP with multi-node support

## Overview

Pi-hole alternative: PowerDNS Recursor + dnstap logging + FastAPI admin UI + Postgres. Modern dark UI, multi-node support, Docker-first.

## Structure

```
powerblockade/
├── admin-ui/           # FastAPI + Jinja2 + SQLAlchemy (main UI, 1600 LOC)
├── dnstap-processor/   # Go service: dnstap → Admin API → Postgres (540 LOC)
├── recursor/           # PowerDNS Recursor config + RPZ zones
├── dnsdist/            # Edge DNS proxy (client IP attribution)
├── sync-agent/         # Secondary node heartbeat (via --profile sync-agent)
├── opensearch/         # Index templates (DEFERRED - not MVP)
├── grafana/            # Dashboard provisioning
├── prometheus/         # Metrics scraping
├── docs/               # DESIGN.md, networking notes
└── scripts/            # init-env.sh
```

## Where to Look

| Task | Location | Notes |
|------|----------|-------|
| Add UI page | `admin-ui/app/main.py` | Modular routers (auth, analytics, blocklists, nodes, forward_zones, precache, metrics, help, client_resolver, jobs) |
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
- **Structure**: `cmd/` entry, `internal/config/`, `internal/buffer/`
- **Deps**: miekg/dns, dnstap, powerdns-protobuf, bbolt
- **Event buffering**: Uses bbolt for store-and-forward pattern (survives primary outages)

### Databases
- **Postgres** runs via postgres:16 image
- Connection via `DATABASE_URL`
- SQLAlchemy 2.0 with async Session

### Docker
- **Network**: `172.30.0.0/16` bridge, static IPs for recursor/dnstap-processor
- **Shared volumes**: `dnstap-socket`, `recursor-control-socket`
- **RPZ sharing**: bind-mount `./recursor/rpz` to admin-ui + dnstap-processor

## Release Process

### Pre-Release Verification (MANDATORY)

Before any release, you MUST deploy and verify on internal test hosts:

| Host | Role | LAN IP | Deploy Command |
|------|------|--------|----------------|
| **celsate** | Primary | `10.5.5.64` | `ssh root@celsate "cd /opt/PowerBlockade && git pull && docker compose up -d --build"` |
| **bowlister** | Secondary | `10.5.5.65` | `ssh root@bowlister "cd /opt/PowerBlockade && git pull && docker compose --profile sync-agent up -d --build"` |

**Verification checklist:**
1. All containers healthy: `docker compose ps`
2. Admin UI loads: `http://10.5.5.64:8080`
3. DNS resolves: `dig @10.5.5.64 google.com`
4. Logs flowing: Check Analytics page shows recent queries
5. Secondary syncing: Check Nodes page shows bowlister heartbeat

**Port 53 conflict note:** Both hosts run netbird which binds port 53 on its interface. dnsdist is configured to bind only to the LAN IP (`DNSDIST_LISTEN_ADDRESS` in `.env`), avoiding conflict.

**RPZ permission fix:** If "Apply" fails with permission error, run `chmod -R 777 recursor/rpz` on the host. This happens when Docker creates the directory as root.

**DO NOT release if deployment fails on either host.**

## Anti-Patterns (DO NOT)

| Pattern | Why |
|---------|-----|
| Release without deploying to celsate/bowlister | Internal hosts catch issues CI cannot |
| Commit `.env` | Contains secrets |
| Use macvlan on WiFi | Broken; use ipvlan L2 or wired |
| Enable Recursor dnstap when using dnsdist | Causes duplicates |
| Complex `command:` in compose | Gets truncated; use entrypoint scripts |
| `pip install --break-system-packages` | Use pipx or venv |
| Passwords > 72 chars without pre-hash | Bcrypt silently truncates |
| `dnsdist newServer()` with hostname | Must use IP literal (e.g., `172.30.0.10:5300`) |
| Primary/secondary sharing same `PRIMARY_API_KEY` in nodes table | Each node needs unique api_key in DB; bootstrap conflict on same key |
| dnstap connection after restart | Must restart dnsdist after dnstap-processor restart to re-establish TCP connection |

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

# E2E Testing (pre-release verification)
./scripts/pb test              # Run against default IPs (10.5.5.64/65)
./scripts/pb test 10.5.5.64 10.5.5.65  # Explicit IPs
NUM_DOMAINS=500 ./scripts/test-e2e.sh  # Test more domains
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ADMIN_SECRET_KEY` | Session signing | required |
| `ADMIN_PASSWORD` | Bootstrap admin user | required |
| `DATABASE_URL` | Postgres DSN | `postgresql+psycopg://...` |
| `RECURSOR_API_KEY` | Recursor webserver auth | required |
| `PRIMARY_API_KEY` | Node auth for dnstap-processor | required for logging |
| `DNSDIST_LISTEN_ADDRESS` | IP for dnsdist to bind port 53 | `0.0.0.0` (all interfaces) |

## Architecture Decisions

- **Postgres-first**: No OpenSearch for MVP (rPi-friendly)
- **Response-only logging**: dnstap CLIENT_RESPONSE only (Pi-hole style)
- **Edge attribution**: dnsdist captures true client IP, not recursor internal
- **Polling reload**: recursor-reloader runs `rec_control` every 5s (not signal-based)

## Known Issues / Tech Debt

### Active Issues
None currently tracked.

### Fixed Issues
- ~~`sync-agent` missing from docker-compose.yml~~ → Available via `--profile sync-agent`
- ~~Containers run as root~~ → Non-root users in Dockerfiles
- ~~Forward zones not reloaded~~ → `reload-fzones` added to recursor-reloader
- ~~No event buffering~~ → dnstap-processor uses bbolt store-and-forward
- ~~No config rollback~~ → Audit trail + rollback UI at `/audit`
- ~~No dashboard charts~~ → ApexCharts integrated
- ~~Grafana ports exposed~~ → Proxied via `/grafana` in admin-ui
- ~~Multi-node metrics missing~~ → sync-agent pushes to primary
- ~~Metrics retention 90 days~~ → Now 365 days default
- ~~Python 3.14 passlib issues~~ → Migrated to direct bcrypt (removed passlib dependency)
- ~~Cache hit threshold hardcoded~~ → Now configurable via `CACHE_HIT_THRESHOLD_MS`
- ~~No latency for protobuf events~~ → Implemented latency calculation from query/response times
- ~~No alerting~~ → Prometheus alertmanager with rules (optional via `--profile alerting`)

## v0.3.x Upgrade System

### Key Features
- **`pb` CLI**: Pi-hole-style upgrade tool (`pb update`, `pb rollback`, `pb status`)
- **Compose split**: `compose.yaml` (vendor) + `compose.user.yaml` (user customizations preserved on upgrade)
- **Version tracking**: `/api/version` endpoint, version in UI footer and System Health page
- **Pre-upgrade backups**: Automatic database backup before upgrades

### Commands
```bash
./scripts/pb status         # Show current version and services
./scripts/pb check-update   # Check for available updates
./scripts/pb update         # Update to latest (backs up DB first)
./scripts/pb rollback       # Revert to previous version
./scripts/pb backup         # Manual backup
```

### Docker Images
- All images use Alpine base (smaller footprint)
- OCI labels for version tracking
- Build args inject version info: `PB_VERSION`, `PB_GIT_SHA`, `PB_BUILD_DATE`

## v0.2.x Observability Stack

### Architecture
- **Push-based metrics**: sync-agent scrapes local recursor, POSTs to primary `/api/node-sync/metrics`
- **Grafana embedded**: Accessed via `/grafana` proxy route in admin-ui
- **Prometheus internal**: Internal network only (expose 9090:9090 if direct access needed)
- **Optional Traefik**: `--profile traefik` for TLS/Let's Encrypt

### New Components
| Component | Location | Purpose |
|-----------|----------|---------|
| `node_metrics` table | `admin-ui/app/models/` | Store metrics from all nodes |
| `/api/node-sync/metrics` | `admin-ui/app/routers/node_sync.py` | Metrics ingestion endpoint |
| `/grafana` proxy | `admin-ui/app/routers/grafana_proxy.py` | Grafana routing via admin-ui |
| System Health page | `admin-ui/app/templates/system.html` | Embedded Grafana dashboard |
| Traefik (optional) | `traefik/traefik.yml` | Edge router with TLS support |

### Key Metrics Collected
- `cache_hits`, `cache_misses` (cache efficiency)
- `answers0_1` through `answers_slow` (latency distribution)
- `concurrent_queries` (current load)
- `outgoing_timeouts`, `servfail_answers` (health indicators)

### Environment Variables
| Variable | Purpose | Default |
|----------|---------|---------|
| `GRAFANA_URL` | Grafana internal URL | `http://grafana:3000` |
| `GRAFANA_ROOT_URL` | Grafana public URL | `http://localhost:8080/grafana/` |
| `DOMAIN` | Domain for Traefik (TLS) | `localhost` |
| `ACME_EMAIL` | Let's Encrypt email | (empty - TLS opt-in) |

### Usage
```bash
# Default: Single entry point on port 8080
docker compose up -d --build
# Access: http://localhost:8080 (includes /grafana proxy)

# Optional: Traefik with TLS
DOMAIN=dns.example.com ACME_EMAIL=admin@example.com docker compose --profile traefik up -d
# Access: https://dns.example.com
```

## Hierarchy

```
./AGENTS.md (this file)
└── admin-ui/AGENTS.md
```
