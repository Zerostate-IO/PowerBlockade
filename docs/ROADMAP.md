# PowerBlockade Roadmap

**Generated:** 2026-01-28
**Last Review:** Full codebase audit with security, CI/CD, testing, and UI analysis
**Updated:** 2026-01-28 (security hardening, nodes page improvements)

This document tracks planned work items for PowerBlockade. Each item includes enough context to resume work later.

---

## High Priority

All high-priority items have been completed! See "Completed Items" section below.

---

## Medium Priority

### 11. NODES: Node Actions

**Status:** Not started
**Effort:** Medium (2-3 hours)

**Problem:** No way to manage nodes from UI (delete, force sync, etc.)

**Actions to add:**
- Delete node (with confirmation)
- Force config sync (bump config_version)
- View metrics history
- Download config package again

**Affected files:**
- `admin-ui/app/templates/nodes.html`
- `admin-ui/app/routers/nodes.py`

**Acceptance criteria:**
- [ ] Delete button with confirmation modal
- [ ] Force sync button
- [ ] Actions require authentication

---

### 13. TESTS: pb CLI Tests

**Status:** COMPLETED
**Effort:** Medium (3-4 hours)

**Solution implemented:** `scripts/test-pb.sh` - Bash unit tests for pb CLI

**Test coverage:**
- `get_current_version` - no state, with state, malformed JSON
- `get_compose_files` - default, user override, legacy docker-compose.yml
- `check_disk_space` - sufficient space check
- `save_state` - JSON creation, overwrite, digest preservation, timestamp format
- `backup_config` - no files, with .env, with shared dirs
- Command tests - help, version, unknown command, status

**Usage:**
```bash
./scripts/test-pb.sh
```

**Acceptance criteria:**
- [x] Test file exists: `scripts/test-pb.sh`
- [x] CI runs pb tests (added to `.github/workflows/tests.yml`)
- [x] Coverage for happy path and error cases (19 tests)

---

### 14. TESTS: Service Layer Tests

**Status:** COMPLETED
**Effort:** Medium (4-6 hours)

**Solution implemented:**
- `tests/unit/test_retention_service.py` - 9 tests for cleanup logic
- `tests/integration/test_rollups_service.py` - 14 tests for rollup computation
- `tests/unit/test_config_audit_service.py` - 12 tests for audit queries
- `tests/integration/test_config_audit_service.py` - 5 tests for record_change

**Note:** Some tests require PostgreSQL (marked `@pytest.mark.integration`) because
services create records without explicit IDs, relying on SERIAL auto-increment.

**Bug fixed:** `rollups.py` was using `func.case()` instead of `case()` - corrected.

**Acceptance criteria:**
- [x] Unit tests for each service
- [x] Integration tests with database

---

### 15. TESTS: Lua Policy Tests

**Status:** Not started
**Effort:** Medium (3-4 hours)

**Problem:** `recursor/rpz.lua` has no automated tests.

**Options:**
1. Use `busted` Lua test framework
2. Integration test with actual recursor container
3. Mock PowerDNS Lua environment

**Acceptance criteria:**
- [ ] RPZ policy logic tested
- [ ] Tests run in CI

---

### 16. TESTS: Full-Stack DNS E2E

**Status:** COMPLETED
**Effort:** Large (6-8 hours)

**Solution implemented:** `scripts/test-e2e.sh` - Comprehensive E2E test suite

**Test coverage:**
1. Connectivity and health checks (primary + secondary)
2. DNS resolution of 100 top domains
3. Ad/tracker blocking verification (10 known blocked domains)
4. Cache performance testing (cold vs warm queries)
5. Precache functionality
6. Query logging verification
7. Multi-node sync testing

**Usage:**
```bash
./scripts/pb test                          # Default IPs
./scripts/pb test 192.168.1.10 192.168.1.11  # Explicit IPs
NUM_DOMAINS=500 ./scripts/test-e2e.sh     # More domains
```

**Acceptance criteria:**
- [x] E2E test script exists
- [x] Tests blocking, allowing, caching
- [x] Tests multi-node sync
- [ ] CI integration (requires internal hosts)

---

### 17. UI: Configurable Precache DNS Resolver

**Status:** COMPLETED
**Effort:** Small (1 hour)

**Solution implemented:**
- Added `precache_dns_server` setting to `app/models/settings.py`
- Added `get_precache_dns_server()` helper function
- Updated `precache_warming_job()` and `trigger_warm_cache` to use the setting
- Added DNS server input field to `precache.html` settings form
- Default value: "recursor" (works in Docker)

**Acceptance criteria:**
- [x] Setting exists in UI
- [x] Precache uses configured server
- [x] Default works in Docker environment

---

## Low Priority

### 18. UI: Real-time Query Streaming

**Status:** COMPLETED
**Effort:** Large (8-12 hours)

**Solution implemented:**
- WebSocket endpoint `/ws/stream` in `app/routers/streaming.py`
- Dashboard "Live Queries" section with start/stop toggle
- Polling-based approach (2s intervals) using `asyncio.to_thread` for sync DB queries
- Auth via user_id query param (validated against users table)
- Shows time, client IP, domain, type, status (blocked/rcode), latency
- Max 50 rows displayed, newest first
- Blocked queries highlighted with red background

**Files created/modified:**
- `admin-ui/app/routers/streaming.py` - WebSocket router
- `admin-ui/app/main.py` - router registration
- `admin-ui/app/templates/index.html` - Live Queries UI + JavaScript client

**Acceptance criteria:**
- [x] WebSocket endpoint exists and authenticates
- [x] Dashboard shows live query stream
- [x] Start/stop toggle works
- [x] Blocked queries visually distinct

---

### 19. UI: Client Grouping

**Status:** COMPLETED
**Effort:** Medium (4-6 hours)

**Solution implemented:**
- New `ClientGroup` model with name, description, CIDR, and color
- `/clients/groups` page to create/edit/delete groups
- Group dropdown on clients page for manual assignment
- Auto-assign feature: matches ungrouped clients to groups by CIDR
- Migration `0011_client_groups.py`

**Files created/modified:**
- `admin-ui/app/models/client_group.py` - new model
- `admin-ui/app/models/client.py` - added group_id FK
- `admin-ui/app/routers/client_groups.py` - new router
- `admin-ui/app/templates/client_groups.html` - new template
- `admin-ui/app/templates/clients.html` - added group dropdown
- `admin-ui/alembic/versions/0011_client_groups.py` - migration

**Acceptance criteria:**
- [x] Groups can be created with name, description, CIDR, color
- [x] Clients can be assigned to groups manually
- [x] Auto-assign by CIDR works
- [x] Groups page shows client count per group

---

### 20. UI: Scheduled Blocklist Categories

**Status:** COMPLETED
**Effort:** Large (6-8 hours)

**Solution implemented:**
- Added schedule fields to Blocklist model: `schedule_enabled`, `schedule_start`, `schedule_end`, `schedule_days`
- Created `blocklist_scheduler.py` service to check schedules and enable/disable blocklists
- Scheduler job runs every 5 minutes to enforce schedules
- Modal UI on blocklists page to configure per-blocklist schedules
- New `/settings` page with timezone selector (used for schedule evaluation)
- Migration `0012_blocklist_schedules.py`

**Files created/modified:**
- `admin-ui/alembic/versions/0012_blocklist_schedules.py` - migration
- `admin-ui/app/services/blocklist_scheduler.py` - schedule enforcement
- `admin-ui/app/services/scheduler.py` - added blocklist_schedule_job
- `admin-ui/app/routers/blocklists.py` - added schedule update endpoint
- `admin-ui/app/routers/settings.py` - new settings router
- `admin-ui/app/models/settings.py` - added timezone default
- `admin-ui/app/templates/blocklists.html` - schedule column and modal
- `admin-ui/app/templates/settings.html` - new settings page

**Acceptance criteria:**
- [x] Blocklists can have time schedules (start, end, days)
- [x] Scheduler enforces schedules every 5 minutes
- [x] Timezone configurable via Settings page
- [x] RPZ regenerated when schedules change blocklist state

---

### 21. UI: Query Log Search

**Status:** COMPLETED
**Effort:** Medium (4-6 hours)

**Solution implemented:**
- Added query type (A, AAAA, MX, etc.) filter dropdown
- Added blocked/allowed status filter dropdown
- Blocked queries highlighted with red background
- Status column shows "Blocked" or rcode
- All filters work together and persist in pagination

**Files modified:**
- `admin-ui/app/routers/analytics.py` - added qtype and blocked params
- `admin-ui/app/templates/logs.html` - added filter dropdowns, status column

**Acceptance criteria:**
- [x] Filter by query type
- [x] Filter by blocked/allowed status
- [x] Blocked queries visually highlighted
- [x] Filters persist across pagination

---

### 22. UI: Mobile Responsive

**Status:** Not started
**Effort:** Medium (4-6 hours)

**Description:** Improve mobile/tablet experience. Currently desktop-optimized.

---

### 23. UI: Theme Toggle

**Status:** COMPLETED
**Effort:** Small (2-3 hours)

**Solution implemented:**
- CSS custom properties for theme colors (bg-900, bg-800, bg-700)
- Theme toggle button in header with sun/moon icons
- localStorage persistence for theme preference
- Early script execution prevents flash of wrong theme

**Files modified:**
- `admin-ui/app/templates/base.html` - theme infrastructure + toggle button

**Acceptance criteria:**
- [x] Toggle button in header
- [x] Light and dark themes work
- [x] Preference persisted across sessions

---

### 24. UI: Backup/Restore in Web UI

**Status:** COMPLETED
**Effort:** Medium (3-4 hours)

**Solution implemented:**
- `/backup` page with create database/config backup buttons
- List of existing backups with download/delete actions
- Database restore via file upload
- Uses pg_dump/psql for database operations
- Config backup creates tarball of RPZ and forward-zones

**Files created:**
- `admin-ui/app/routers/backup.py` - backup router
- `admin-ui/app/templates/backup.html` - backup UI

**Acceptance criteria:**
- [x] Create database backup
- [x] Create config backup  
- [x] Download existing backups
- [x] Delete backups
- [x] Restore database from upload

---

### 25. FEATURE: DNS-over-HTTPS/TLS

**Status:** Not started
**Effort:** Large (8-12 hours)

**Description:** Add DoH/DoT support via dnsdist for encrypted DNS.

---

### 26. FEATURE: API Rate Limiting

**Status:** CANCELLED
**Effort:** Medium (2-3 hours)

**Reason:** PowerBlockade is a private network admin tool with no public-facing endpoints. All API access is internal (node sync) or authenticated (admin UI). Rate limiting adds complexity without benefit.

---

### 27. FEATURE: Prometheus Alert Presets

**Status:** COMPLETED
**Effort:** Medium (3-4 hours)

**Solution implemented:**
Added additional alert rules to `prometheus/alerts.yml`:
- `HighQueryLatency` - >10% queries with >1s latency
- `HighBlockRate` - >50% block rate (possible malware)
- `HighNXDOMAINRate` - >20% NXDOMAIN (possible DGA)
- `ConcurrentQueriesHigh` - >500 concurrent (amplification check)
- `NodeNotSyncing` - secondary node heartbeat stale

Existing alerts (already present):
- `LowCacheHitRate` / `CriticalCacheHitRate`
- `HighServfailRate` / `HighTimeoutRate`
- `NodeMetricsStale` / `RecursorDown`

**Files modified:**
- `prometheus/alerts.yml` - added 5 new alert rules

**Acceptance criteria:**
- [x] Alert rules for latency issues
- [x] Alert rules for security indicators (high block rate, NXDOMAIN)
- [x] Alert rules for capacity issues (concurrent queries)
- [x] Alert rules for multi-node sync

---

### 28. SECURITY: Auth-gate Version Endpoint

**Status:** COMPLETED
**Effort:** Small (30 min)

**Description:** `/api/version` exposes Git SHA which aids fingerprinting. Now restricted to authenticated users (session required in `admin-ui/app/main.py`).

---

## Completed Items

### 1. SECURITY: Add CSRF Protection (COMPLETED)
- Added custom CSRF middleware (`admin-ui/app/csrf.py`)
- Uses Double Submit Cookie pattern
- All forms include `{{ csrf_input(request) }}`
- API endpoints exempt (use their own auth)

### 2. SECURITY: Harden Session Cookies (COMPLETED)
- SessionMiddleware now uses `same_site="lax"`
- `httponly` flag set by default in Starlette

### 3. SECURITY: Fail on Default Credentials (COMPLETED)
- Added `validate_security_settings()` in main.py
- Refuses to start with default passwords unless `POWERBLOCKADE_ALLOW_INSECURE=true`

### 4. CI: Fix tests.yml Workflow (COMPLETED)
- Updated `astral-sh/setup-uv@v4`
- Fixed pytest invocation

### 5. NODES: sync-agent Send IP and Version (COMPLETED)
- Added `get_local_ip()` and `get_version()` to sync-agent
- Nodes page now shows IP and version

### 6. NODES: Human-Readable Timestamps (COMPLETED)
- Added `timeago` Jinja2 filter in `template_utils.py`
- Shows "2 minutes ago" style timestamps

### 7. CODE: Replace Silent Exception Handlers (COMPLETED)
- Fixed `ptr_resolver.py:60` and `scheduler.py:99`
- Now logs warnings instead of silently ignoring errors

### 8. NODES: Status Badges with Colors (COMPLETED)
- Green: active (seen within 5 minutes)
- Yellow: stale (not seen in 5+ minutes)
- Red: error (has last_error)
- Gray: pending (never seen)

### 9. NODES: Additional Metrics Columns (COMPLETED)
- Added Queries Total, Queries Blocked, Cache Hit %
- Numbers formatted with commas

### 10. NODES: Error Row Details (COMPLETED)
- Shows last_error in expandable row under node

### 12. NODES: Primary Node Badge (COMPLETED)
- Primary node shows indigo "primary" badge

### 16. TESTS: Full-Stack DNS E2E (COMPLETED)
- `scripts/test-e2e.sh` - comprehensive E2E test suite
- Tests connectivity, resolution, blocking, caching, multi-node sync

### 13. TESTS: pb CLI Tests (COMPLETED)
- `scripts/test-pb.sh` - Bash unit tests for pb CLI
- Tests: version parsing, compose file detection, state management, backup logic
- 19 tests covering happy path and error cases
- CI integration in `.github/workflows/tests.yml`

### 14. TESTS: Service Layer Tests (COMPLETED)
- `tests/unit/test_retention_service.py` - 9 tests for cleanup logic
- `tests/integration/test_rollups_service.py` - 14 tests for rollup computation
- `tests/unit/test_config_audit_service.py` - 12 tests for audit queries
- `tests/integration/test_config_audit_service.py` - 5 tests for record_change
- Bug fixed: `rollups.py` was using `func.case()` instead of `case()`

### 17. UI: Configurable Precache DNS Resolver (COMPLETED)
- Added `precache_dns_server` setting with default "recursor"
- UI input in precache settings form
- No longer hardcoded to 127.0.0.1

### 18. UI: Real-time Query Streaming (COMPLETED)
- WebSocket endpoint `/ws/stream` with polling-based DB queries
- Dashboard "Live Queries" section with start/stop toggle
- Auth via user_id validated against users table
- Shows time, client, domain, type, status, latency
- Blocked queries highlighted in red

### 19. UI: Client Grouping (COMPLETED)
- `ClientGroup` model with name, description, CIDR, color
- Groups page at `/clients/groups` for CRUD operations
- Manual group assignment via dropdown on clients page
- Auto-assign by CIDR matching

### 23. UI: Theme Toggle (COMPLETED)
- CSS custom properties for theme colors
- Toggle button in header with sun/moon icons
- localStorage persistence

### 24. UI: Backup/Restore in Web UI (COMPLETED)
- `/backup` page with create/download/delete/restore
- Database backup via pg_dump, restore via psql
- Config backup as tarball

### 21. UI: Query Log Search (COMPLETED)
- Query type filter (A, AAAA, MX, etc.)
- Blocked/allowed status filter
- Blocked queries highlighted in red
- All filters persist across pagination

### 27. Prometheus Alert Presets (COMPLETED)
- 5 new alert rules: latency, block rate, NXDOMAIN, concurrent queries, node sync
- Total of 11 alert rules for comprehensive DNS monitoring

### 20. UI: Scheduled Blocklist Categories (COMPLETED)
- Blocklist model extended with schedule fields
- Scheduler job enforces schedules every 5 minutes
- Settings page with timezone selector
- Modal UI on blocklists page for schedule configuration

---

## Notes

- All times are estimates
- Docker-only deployment assumed (no bare-metal support planned)
- UI configurability is a priority - minimize need for env vars/config files
- Test on primary and secondary nodes before any release
