# Admin UI Knowledge Base

FastAPI web interface + API for PowerBlockade. Handles config, blocklists, analytics, node management.

## Structure

```
admin-ui/
├── app/
│   ├── main.py           # FastAPI app setup, router registration, lifespan
│   ├── settings.py       # pydantic-settings config
│   ├── security.py       # bcrypt + SHA256 pre-hash
│   ├── presets.py        # Built-in blocklist definitions
│   ├── models/           # SQLAlchemy 2.0 models
│   ├── routers/          # Modular API and page routers
│   ├── services/         # Business logic (rpz, rollups, scheduler, etc.)
│   ├── templates/        # Jinja2 (base.html + pages)
│   └── db/               # session.py, base.py
├── alembic/              # DB migrations
├── pyproject.toml        # uv/ruff config
└── Dockerfile
```

## Routers

| Router | Prefix | Purpose |
|--------|--------|---------|
| `auth` | `/` | Login/logout, session management |
| `analytics` | `/` | Dashboard, logs, clients, domains, blocked, failures |
| `blocklists` | `/` | Blocklist CRUD, Apply, setup page |
| `nodes` | `/` | Node management, package generator |
| `node_sync` | `/api/node-sync` | API for secondary nodes (register, heartbeat, ingest, config, metrics) |
| `forward_zones` | `/` | Forward zone CRUD |
| `client_resolver` | `/` | PTR resolution rules |
| `precache` | `/` | Cache analytics |
| `metrics` | `/` | Prometheus metrics endpoint |
| `jobs` | `/` | Manual job triggers (rollup, retention) |
| `audit` | `/` | Config change history |
| `system` | `/` | System health page |
| `grafana_proxy` | `/grafana` | Proxy to embedded Grafana |
| `help` | `/help` | Contextual help pages |

## Models

| Model | Table | Purpose |
|-------|-------|---------|
| `User` | `users` | Admin auth |
| `Blocklist` | `blocklists` | URL + format + enabled + update_frequency |
| `ManualEntry` | `manual_entries` | Whitelist/blacklist domains |
| `Client` | `clients` | IP + rdns_name + display_name |
| `ClientResolverRule` | `client_resolver_rules` | Subnet → DNS server for PTR |
| `DNSQueryEvent` | `dns_query_events` | Query log storage |
| `QueryRollup` | `query_rollups` | Hourly/daily aggregates |
| `Node` | `nodes` | Secondary node registration |
| `NodeMetrics` | `node_metrics` | Pushed metrics from nodes |
| `ForwardZone` | `forward_zones` | Domain overrides |
| `Settings` | `settings` | Key-value config |
| `ConfigChange` | `config_changes` | Audit trail |

## Services

| Service | File | Purpose |
|---------|------|---------|
| RPZ | `rpz.py` | Parse blocklists, render RPZ zones |
| Forward Zones | `forward_zones.py` | Generate recursor config |
| PTR Resolver | `ptr_resolver.py` | Background client name resolution |
| Rollups | `rollups.py` | Compute hourly/daily query aggregates |
| Retention | `retention.py` | Cleanup old events, rollups, metrics |
| Scheduler | `scheduler.py` | APScheduler background jobs |
| Node Generator | `node_generator.py` | Create secondary node packages |
| Config Audit | `config_audit.py` | Record config changes |

## Background Jobs (APScheduler)

| Job | Schedule | Purpose |
|-----|----------|---------|
| `blocklist_update` | Every 15 min | Check and update blocklists due for refresh |
| `rollup` | Hourly (minute 5) | Compute query rollups |
| `retention` | Daily (3:00 AM) | Delete old events/rollups/metrics |

## API Endpoints

### Node Sync API (for secondary nodes)

```
POST /api/node-sync/register    # Node registers with API key
POST /api/node-sync/heartbeat   # Node health check
POST /api/node-sync/ingest      # Batch event ingestion
GET  /api/node-sync/config      # Pull RPZ, forward zones, settings
POST /api/node-sync/metrics     # Push recursor metrics
```

Auth: `X-PowerBlockade-Node-Key` header → matches `nodes.api_key`

## Conventions

- **Routes**: Return `RedirectResponse` after form POST, `HTMLResponse` for pages
- **Auth check**: `get_current_user()` at top of each route
- **Templates**: `{"request": request, "user": user, ...}` context
- **Form handling**: `Form(...)` params, validate manually
- **Blocklist apply**: Downloads URLs → parses → writes RPZ files to `/shared/rpz/`
- **Config audit**: Use `record_change()` for any config modifications

## Anti-Patterns

- No `@ts-ignore` equivalent - fix type errors properly
- No raw SQL in routes - use models
- No secrets in templates - env vars only
- Passwords must use `hash_password()` (handles 72-byte limit)

## Commands

```bash
uv sync                        # Install deps
alembic upgrade head           # Apply migrations
alembic revision --autogenerate -m "desc"  # New migration
uvicorn app.main:app --reload  # Dev server (port 8000)
ruff check .                   # Lint
ruff format .                  # Format
```

## Bootstrap Behavior

On startup (`lifespan`):
1. `bootstrap_admin()` - Creates admin user if missing
2. `bootstrap_primary_node()` - Creates "primary" node row if `PRIMARY_API_KEY` set
3. `start_scheduler()` - Starts APScheduler for background jobs

## Gotchas

1. Templates use relative imports from `app/templates/`
2. RPZ files written to `/shared/rpz/` (bind-mounted in Docker)
3. `Blocklist.list_type` can be "block" or "allow" (whitelist support)
4. `Blocklist.update_frequency_hours` controls auto-update schedule (0 = manual)
5. `DNSQueryEvent.event_id` is unique - enables idempotent retry from nodes
6. Scheduler runs in-process - no external cron needed
