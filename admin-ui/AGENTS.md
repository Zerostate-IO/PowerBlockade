# Admin UI Knowledge Base

FastAPI web interface + API for PowerBlockade. Handles config, blocklists, analytics, node management.

## Structure

```
admin-ui/
├── app/
│   ├── main.py           # ALL routes (monolithic - known debt)
│   ├── settings.py       # pydantic-settings config
│   ├── security.py       # bcrypt + SHA256 pre-hash
│   ├── presets.py        # Built-in blocklist definitions
│   ├── models/           # SQLAlchemy 2.0 models
│   ├── routers/          # Only node_sync.py lives here (should have more)
│   ├── services/         # rpz.py (blocklist parsing), node_generator.py
│   ├── templates/        # Jinja2 (base.html + pages)
│   └── db/               # session.py, base.py
├── alembic/              # DB migrations
├── pyproject.toml        # uv/ruff config
└── Dockerfile
```

## Where to Look

| Task | File | Notes |
|------|------|-------|
| Add new page | `app/main.py` | Add route + template |
| Add API endpoint | `app/routers/node_sync.py` | Or create new router |
| Add DB table | `app/models/` | New file, import in migration |
| Parse blocklist format | `app/services/rpz.py` | `parse_blocklist_text()` |
| Change auth flow | `app/security.py` + `app/main.py` | Session in `/login` |
| Modify template | `app/templates/` | Extends `base.html` |

## Models

| Model | Table | Purpose |
|-------|-------|---------|
| `User` | `users` | Admin auth |
| `Blocklist` | `blocklists` | URL + format + enabled flag |
| `ManualEntry` | `manual_entries` | Whitelist/blacklist domains |
| `Client` | `clients` | IP + rdns_name + display_name |
| `DNSQueryEvent` | `dns_query_events` | Query log storage |
| `Node` | `nodes` | Secondary node registration |

## API Endpoints

```
POST /api/node-sync/register   # Node registers with API key
POST /api/node-sync/heartbeat  # Node health check
POST /api/node-sync/ingest     # Batch event ingestion
GET  /api/node-sync/config     # (placeholder) Config download
```

Auth: `X-PowerBlockade-Node-Key` header → matches `nodes.api_key`

## Conventions

- **Routes**: Return `RedirectResponse` after form POST, `HTMLResponse` for pages
- **Auth check**: `get_current_user()` at top of each route
- **Templates**: `{"request": request, "user": user, ...}` context
- **Form handling**: `Form(...)` params, validate manually
- **Blocklist apply**: Downloads URLs → parses → writes RPZ files to `/shared/rpz/`

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

## Gotchas

1. Templates use relative imports from `app/templates/`
2. RPZ files written to `/shared/rpz/` (bind-mounted in Docker)
3. `Blocklist.list_type` can be "block" or "allow" (whitelist support)
4. `DNSQueryEvent.event_id` is unique - enables idempotent retry from nodes
