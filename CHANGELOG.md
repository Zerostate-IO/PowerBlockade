# Changelog

All notable changes to PowerBlockade are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

See [Release Policy](docs/RELEASE_POLICY.md) for version compatibility guarantees.

## [0.10.0] - 2026-08-19

> **Release Type**: Minor Release
> **Upgrade Safety**: Safe upgrade; migration `0019` (precache settings data
> migration) applies automatically on admin-ui start. Operators should set
> `RECURSOR_WEB_PASSWORD` and `DNSDIST_WEB_PASSWORD` in `.env` (see below) —
> without them the metrics webservers generate a random per-start password and
> stay authenticated, but Prometheus scraping returns 401 until values are set
> and the stack is restarted. The recursor webserver port 8082 is no longer
> published to the host; scraping happens inside the compose network.

### Added

- **Sub-millisecond edge latency observability**: dnstap-processor exposes a
  Prometheus `/metrics` endpoint (port 9422) with a real-traffic response
  latency histogram (`dnstap_processor_response_latency_seconds`, buckets
  0.1–10 ms — the only sub-ms-capable source in the stack; native PowerDNS
  histograms bottom out at 1 ms), plus event/buffer health counters. Fixes a
  precision bug where sub-millisecond latencies were truncated to integer
  milliseconds (zeroed).
- **Synthetic warm-path prober**: new `prober` service (static IP 172.30.0.30)
  continuously queries a frozen 10,000-domain Cisco Umbrella control corpus
  through the dnsdist edge and reports client-observed latency on port 9533.
  Prober traffic is isolated end-to-end: labeled series (`prober="true"`),
  separate dashboard panels, excluded from analytics (internal subnet), and —
  by default — dropped from event shipping (`DROP_PROBER_EVENTS=true`) while
  still counting in metrics.
- **Authenticated, private metrics listeners**: recursor and dnsdist
  webservers now require basic auth (`RECURSOR_WEB_PASSWORD`,
  `DNSDIST_WEB_PASSWORD`); recursor `:8082` is no longer published to the
  host (fixes an information-exposure finding: `/metrics` previously served
  client DNS data unauthenticated to any network that could reach the host).
  Unset passwords generate a random per-start value with a loud warning —
  the webserver never starts passwordless. dnsdist metrics webserver added
  at `:8083` (in-network only).
- **Prometheus/Grafana visibility**: five scrape jobs (admin-ui, recursor,
  dnsdist, dnstap-processor, prober) with credential files; "DNS Performance"
  Grafana dashboard (per-layer cache hit ratios, production p50/p90/p99,
  occupancy vs capacity, processor health, isolated prober panels); new
  `powerblockade-primary` alert group (prober absence, buffer backlog,
  shipping lag, drops). Secondary-node push-path alerts unchanged.
- **Boot warm burst**: on admin-ui startup, once dnsdist and recursor are
  ready, a bounded warm pass runs over the top observed pairs (concurrency
  and QPS ceilings, jitter, dedup, backoff, shared advisory lock with the
  scheduled warming job). Status via `GET /precache/boot-burst` and the
  precache page; settings `precache_boot_burst_{enabled,concurrency,qps}`.
- **Fail-closed benchmark harness** (`dns53-benchmark.sh` v2): dual-layer
  cache clearing (dnsdist console `expunge(0)` + `rec_control wipe-cache`)
  with floor verification, per-layer counter-delta hit ratios, p99 gating,
  dnsperf ≥ 2.14.0 version validation, precache quiesce with symmetric
  restore, and a time-to-warm mode; `--self-test` offline. Opt-in dnsdist
  console (`DNSDIST_CONSOLE_KEY`, localhost-only inside the container).
- **Measured performance baselines** committed under
  `docs/performance/results/`: cold p50/p95/p99 0.099/0.159/0.287 ms; warm
  0.049/0.093/0.147 ms at 99.9% dnsdist packet-cache hit ratio; saturation
  8,497 QPS sustained at 0.01% errors; time-to-warm 185 s (six windows run,
  five consecutive passing windows of 30 s).

### Changed

- **Precache warming heats both cache layers**: warming now targets
  `dnsdist:53` (was `recursor:5300`, which left the edge cache cold) and
  warms observed `(qname, qtype)` pairs (A, AAAA, HTTPS/65…) ranked by
  actual demand, with per-pair TTL tracking and a per-pass query ceiling
  (`precache_max_queries_per_pass`, default 2000). Stored settings rows
  still pointing at the old defaults are migrated by migration `0019`.
- **Longer stale-serving window**: dnsdist `staleTTL`/`setStaleCacheEntriesTTL`
  raised 60 s → 300 s, plus `keepStaleData=true` — without which stale
  serving was silently defeated by the cache cleaner (live-verified effective
  window was ≤31 s). Upstream outages now serve cached answers for up to
  5 minutes instead of failing; deliberate availability-over-freshness
  trade (rollback values documented in the template).
- **ECS no longer sent upstream**: dnsdist `useClientSubnet=false` — the
  recursor discards the option anyway (its `use-incoming-edns-subnet`
  defaults false with an empty allow-list), so the per-miss ECS computation
  was dead overhead (experiment E2: hit ratio unchanged at 99.9%).
- Time-to-warm "warm" criterion gates inner-layer warmth on recursor
  occupancy (stored heat) rather than inner hit ratios: behind a ~99.7% edge,
  inner-layer ratios are sparse-sample noise by architecture.

### Fixed

- Benchmark harness: "cold" runs previously flushed only the recursor (dnsdist
  packet-cache hits made "cold" runs warm), ignored flush failures, computed
  hit ratios from lifetime counters, and silently nulled percentiles on
  unrecognized dnsperf output. Also: `--mode all` now includes time-to-warm;
  dnsperf version probing works across builds (2.15.0 prints the version only
  in the run banner).
- Benchmark quiesce handles deployments with no stored
  `precache_enabled` settings row (fresh installs): upsert + symmetric
  restore, instead of warning and skipping the quiesce.
- sync-agent and the admin-ui local-metrics job now authenticate to the
  recursor `/metrics` endpoint (they previously relied on it being
  passwordless and would have silently 401'd after this release's auth).

### Notes

- **New environment variables**: `RECURSOR_WEB_PASSWORD`,
  `DNSDIST_WEB_PASSWORD` (recommended; charset `[A-Za-z0-9._~+=@-]`),
  `DNSDIST_CONSOLE_KEY` (optional; exact base64 from
  `head -c 32 /dev/urandom | base64 -w0`), `DROP_PROBER_EVENTS` (default
  true), `METRICS_LISTEN`, `PROBER_IPS`.
- **SELinux-enforcing hosts** must label bind-mounted directories
  (`chcon -R -t container_file_t …`) or container startup fails on the
  read-only mounts; permissive hosts are unaffected.
- Known follow-ups (not in this release): CI build step for the prober
  image; secondary-node package regeneration with the new auth/warming
  plumbing; removal of the unused `recursor/recursor.conf` file.

## [0.9.0] - 2026-08-18

> **Release Type**: Minor Release
> **Upgrade Safety**: Safe upgrade; migration 0018 (`is_internal` column) applies
> automatically on admin-ui start. No manual steps. Secondary nodes should
> re-deploy from a freshly generated thin package to pick up the
> `INTERNAL_SUBNETS` wiring.

### Added

- **Internal-traffic flag (`is_internal`, issue #48)**: dnstap-processor flags
  events whose client is in an internal subnet (docker network etc.); the
  analytics views (logs, domains, blocked, failures, history), client
  dropdowns, dashboard rollups and raw-edge aggregates, the live query stream,
  node counts, and precache stats exclude them by default, with a "Show
  internal" toggle (`?include_internal=1`) on logs and domains. Per-node
  config via `INTERNAL_SUBNETS` (compose defaults it to `DOCKER_SUBNET`).
  Secondary precache warming no longer drowns the query log with container
  IPs. Regression gate's internal-exclusion check fixed (missing column +
  missing `::inet` cast + CIDR validation).

### Fixed

- Fresh installs no longer fail postgres authentication: `init-env.sh` now
  regenerates `DATABASE_URL` in sync with the generated `POSTGRES_PASSWORD`
  (previously the `.env.example` default `change-me` was left in the URL,
  breaking admin-ui against a freshly initialized database)
- `init-env.sh` `set_kv` no longer interpolates `@`/`$` in perl substitution
  (values like `postgresql+psycopg://...@postgres:...` were corrupted)
- Generated secondary packages now unpack with correct file modes
  (entrypoint 0755, configs 0644, `.env` 0600) and include the
  `init-permissions` ownership bootstrap, so containers running as non-root
  users (`pdns`, uid 1000) can read/write the mounted configs — observed on
  the bowlister v0.8.0 deploy

### Changed

- admin-ui now has a `/health` readiness healthcheck in both compose files
  (it runs alembic migrations before uvicorn listens)
- Release runtime gate: `!override` port mapping (was appending and binding
  `0.0.0.0:53` on runners), 240s admin-health poll, failure diagnostics dump,
  CSRF-aware login POST (urlencoded)
- Dependabot refresh: 25 dependency PRs merged/reapplied — GitHub Actions
  bumps (checkout 6, setup-python 6, setup-go 6, setup-uv 7, build-push 7,
  metadata 6, buildx 4, qemu 4, upload-artifact 7, github-script 8), Docker
  base images (python 3.14-alpine, golang 1.26, alpine 3.23), and constraint
  floors (fastapi 0.135.3, pydantic 2.12.5, psycopg 3.3.3, httpx 0.28.1,
  pytest 9.0.3, apscheduler 3.11.2, jinja2 3.1.6, dnspython 2.8.0,
  requests 2.33.1, miekg/dns 1.1.72, bbolt 1.4.3, go-powerdns-protobuf 1.6.1,
  pytest-playwright 0.7.2, pytest-asyncio 1.3.0, python-multipart 0.0.26)

## [0.8.0] - 2026-08-17


> **Release Type**: Minor Release
> **Upgrade Safety**: Safe upgrade; secondary nodes should be re-deployed from a
> freshly generated thin package (see docs). No database migrations.

### Fixed

- **Power-cycle DNS outages**: dnsdist now waits for the recursor first and fails closed (exits instead of serving SERVFAIL without a backend); the dnstap-monitor restart loop that killed/restarted dnsdist repeatedly during boot (observed 4+ times in one boot on celsate) is removed — the framestream logger reconnects on its own
- **Stale recursor control socket**: recursor entrypoint removes leftover `pdns_recursor.controlsocket`/`pdns_recursor.pid` files from unclean shutdowns, which previously broke the `rec_control` healthcheck and the stack's readiness gating
- **Secondary node packages**: generated packages now pin dnsdist 2.0.8 (2.0.x has a mandatory April 2026 security advisory), pin `POWERBLOCKADE_VERSION` to the release instead of `latest`, fail closed when the recursor is unavailable, drop the no-op `--profile secondary` startup command, and persist the sync-agent metrics buffer
- **`pb` CLI**: version was stale (0.7.6), compose-file selection ignored `docker-compose.ghcr.yml`, and config backups targeted nonexistent `shared/` paths (producing empty archives); backup paths, compose selection, and DB/user name handling corrected
- Restored the missing v0.7.9 changelog entry

### Changed

- Image pins refreshed (audited 2026-08-17): dnsdist 2.0.8, postgres 16.15-alpine, prometheus v3.13.2, alertmanager v0.34.0, grafana 13.1.3, traefik v3.7.10, busybox 1.38.0, pdns-recursor-53 base 5.3.10
- dnsdist container raises its file-descriptor limit (default 65536) to match its >10000-FD configuration needs

### Security

- dnsdist updated to 2.0.8 (mandatory advisory: powerdns-advisory-for-dnsdist-2026-04)
- Recursor base image pinned to 5.3.10 (celsate's locally-built recursor was running 5.1.9 with a mandatory security advisory due to a stale cached `latest` base)

## [0.7.9] - 2026-05-10

> **Release Type**: Patch Release (Bugfix)
> **Upgrade Safety**: Safe upgrade, no manual steps required

### Fixed

- Dashboard and Prometheus stats now come from bounded rollup-backed stats service, avoiding unbounded aggregation queries under load
- Reduced Prometheus scrape pressure by serving dashboard stats from bounded rollups

### Changed

- Release workflow now builds the `powerblockade-recursor-reloader` image for releases (was missing from the GHCR manifest)
- RPZ tests patch the bound templates instance to stay compatible with newer template runtimes

## [0.7.8] - 2026-04-20

> **Release Type**: Patch Release (Bugfix)
> **Upgrade Safety**: Safe upgrade, no manual steps required
> **Supersedes**: v0.7.7 for admin-ui compatibility with newer FastAPI/Starlette template rendering APIs

### Fixed

- Admin UI server-rendered pages now render correctly when the container resolves newer FastAPI/Starlette versions that require the `TemplateResponse(request, name, context=...)` calling convention

### Changed

- Release runtime gate now verifies anonymous `GET /` and `GET /login` before publishing images so page-render regressions are caught before release

### Upgrade Instructions

```bash
POWERBLOCKADE_VERSION=0.7.8 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.8 docker compose -f docker-compose.ghcr.yml up -d
```

## [0.7.7] - 2026-04-17

> **Release Type**: Patch Release (Bugfix)
> **Upgrade Safety**: Safe upgrade, no manual steps required
> **Supersedes**: v0.7.6 for fresher blocked-event classification and release publication fixes

### Changed

- dnstap-processor now reloads RPZ and allowlist sets at most once per second instead of every five seconds, reducing stale blocked-event tagging after config changes
- Release automation now uses a blocking runtime gate that avoids GitHub-hosted runner port-53 conflicts while keeping the full install-path smoke test as advisory verification

### Documentation

- Updated version-pinning and upgrade examples to target v0.7.7
- Clarified help text to match trigger-driven recursor reload behavior

### Upgrade Instructions

```bash
POWERBLOCKADE_VERSION=0.7.7 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.7 docker compose -f docker-compose.ghcr.yml up -d
```

## [0.7.6] - 2026-04-15

> **Release Type**: Patch Release (Bugfix)
> **Upgrade Safety**: Safe upgrade, no manual steps required
> **Supersedes**: v0.7.5 for environments that rely on forward-zone live reloads

### Fixed

- Recursor reloader sidecar now correctly detects changes to bind-mounted `forward-zones.conf` (inotify watch was not firing for bind-mounted files on Docker hosts)

### Upgrade Instructions

v0.7.6 is the recommended rollout target for all environments. Environments that use forward-zone live reloads should upgrade from v0.7.5.

```bash
POWERBLOCKADE_VERSION=0.7.6 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.6 docker compose -f docker-compose.ghcr.yml up -d
```

## [0.7.5] - 2026-04-15

> **Release Type**: Patch Release (Bugfix)
> **Upgrade Safety**: Safe upgrade, no manual steps required
> **Supersedes**: v0.7.4 secondary-package generation was broken; use v0.7.5 for any secondary node deployments. For forward-zone live reloads, use v0.7.6 instead.

### Fixed

- Generated secondary node packages now produce correct dnsdist backend addressing (was emitting invalid listen/bind configuration that prevented dnsdist startup on secondary nodes)
- Generated secondary node packages now use the correct static-IP and network contract so the secondary node's dnsdist binds to the intended LAN address instead of failing or binding to the wrong interface
- Node generator (`admin-ui/app/services/node_generator.py`) now matches the canonical compose health and dependency contract validated in v0.7.3

### Upgrade Instructions

Secondary nodes deployed from v0.7.4 generated packages must be re-deployed from a fresh v0.7.5 package.

```bash
POWERBLOCKADE_VERSION=0.7.5 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.5 docker compose -f docker-compose.ghcr.yml up -d
```

## [0.7.4] - 2026-04-15

> **Release Type**: Patch Release
> **Upgrade Safety**: Safe upgrade for primary nodes. Secondary node packages generated from v0.7.4 contain dnsdist addressing bugs; upgrade to v0.7.5 before deploying any secondary nodes.

### Added

- Dedicated `recursor-reloader` sidecar watches RPZ files and `forward-zones.conf` via inotify and runs `rec_control reload-lua-config` only when files actually change, eliminating unnecessary recursor load
- `powerblockade-recursor-reloader` image published to GHCR alongside existing component images

### Changed

- RPZ files on the primary are now written with `atomic_write()` (atomic replace via temp file) so the reloader sidecar sees clean inotify events instead of partial writes
- `forward-zones.conf` is now written with `safe_write()` (in-place overwrite preserving inode) so Docker file bind mounts stay consistent
- Generated secondary node packages now reference the official `powerblockade-recursor-reloader` GHCR image and use `docker-compose.ghcr.yml` as the compose file

### Fixed

- Replaced continuous 5-second `rec_control` polling with a dedicated file-watch sidecar that reloads the recursor only when config files change

### Upgrade Instructions

```bash
POWERBLOCKADE_VERSION=0.7.4 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.4 docker compose -f docker-compose.ghcr.yml up -d
```

## [0.7.3] - 2026-04-03

> **Release Type**: Patch Release
> **Upgrade Safety**: Safe upgrade, no manual steps required

### Changed

- dnsdist startup now waits for recursor readiness before accepting queries and fails fast if port 53 is not reachable inside the container
- dnsdist and recursor now use health-gated startup ordering so reboot recovery does not depend on container start order alone
- Generated secondary deployment packages now use the same health and dependency contract as the canonical compose files

### Fixed

- Post-reboot DNS outages where recursor was healthy but dnsdist never became reachable on the intended LAN IP
- dnsdist healthchecks on official images that do not ship with `dig`
- recursor healthchecks that treated lowercase `pong` responses as failures on live hosts

### Documentation

- Added reboot recovery verification guidance for LAN-IP testing, health checks, and dnsdist troubleshooting in deployment and getting-started docs
- Documented the live-validated distinction between VPN resolver success and PowerBlockade DNS reachability

### Validation

- Verified on `10.5.5.2` and `10.5.5.3` after a real power outage: `recursor` healthy, `dnsdist` healthy, and `dig @10.5.5.x google.com +short` succeeds locally and remotely

### Upgrade Instructions

```bash
POWERBLOCKADE_VERSION=v0.7.3 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=v0.7.3 docker compose -f docker-compose.ghcr.yml up -d
```

## [0.7.2] - 2026-03-03

> **Release Type**: Minor Feature Release
> **Upgrade Safety**: Safe upgrade, see Known Issues below

### Added

- Node lifecycle management with automatic state transitions (healthy → offline → quarantined)
- Quarantine-on-return for nodes offline >24 hours (configurable via `health_quarantine_threshold_minutes`)
- Metrics buffering for secondary nodes (7-day retention during primary outages)
- Version compatibility warnings in sync protocol (MINOR version skew = WARN, MAJOR = BLOCK)
- Scheduler job state tracking with PostgreSQL advisory locks

### Changed

- **BREAKING-ADJACENT**: Container startup now validates security settings
  - Installs with default/weak credentials will fail to start
  - Bypass available: `POWERBLOCKADE_ALLOW_INSECURE=true` (development only)
- Secondary node sync protocol now handles mixed-version deployments gracefully

### Fixed

- Advisory lock race conditions in scheduler jobs
- Secondary node compatibility with version skew during rolling upgrades

### Known Issues

- `pb rollback` does not automatically restore previous Docker image versions
  - **Workaround**: See [Manual Rollback Procedure](docs/UPGRADE.md#manual-rollback-procedure)

### Upgrade Instructions

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

---


## [0.7.1] - 2026-02-26

> **Release Type**: Patch Release
> **Upgrade Safety**: Safe upgrade, no manual steps required

### Added

- DNS53 benchmark script (`scripts/benchmark-dns53.sh`) with cold/warm/saturation test phases and configurable target QPS
- Rollback command pack documentation for staged deployments (`docs/ROLLBACK_COMMAND_PACKS.md`)
- Local gate runner script (`scripts/run-local-gates.sh`) for pre-deployment validation

### Changed

- DNS cache tuning configuration with explicit dnsdist `newPacketCache` parameters and recursor `refresh-on-ttl-perc` tuning
- Cache configuration includes inline rollback comments for quick restoration to defaults

### Validation

- Staged rollout completed: bowlister (secondary) validated for 30-minute soak, then celsate (primary) validated
- Rollback rehearsals passed on both nodes
- All local gate checks passed before promotion

### Upgrade Instructions

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

---

> **Release Type**: Feature Release
> **Upgrade Safety**: See Operator Action Required below

### Added

- Multi-node architecture with centralized telemetry (query logs and metrics ship to primary)
- Sync-agent for secondary node configuration sync and health monitoring
- Event buffering on secondary nodes (bbolt store-and-forward for network partitions)
- Node metrics collection (uptime, query counts, cache stats)
- CI docs consistency checks workflow
- Upgrade validation checklist

### Changed

- **BREAKING**: Multi-node telemetry now ships to primary (query logs and metrics centralized)
  - Previous docs incorrectly stated these stayed local
  - See [Multi-Node Architecture](docs/MULTI_NODE_ARCHITECTURE.md) for data flow
- Heartbeat interval default changed from 30s to 60s (configurable via `HEARTBEAT_INTERVAL_SECONDS`)
- docker-compose.ghcr.yml now uses configurable subnet/IPs via env vars
- docker-compose.ghcr.yml now supports version pinning via `POWERBLOCKADE_VERSION`
- Release workflow sed pattern fixed for settings.py format

### Fixed

- Fixed "What Stays Local" section in GETTING_STARTED.md (telemetry ships to primary)
- Fixed heartbeat interval documentation (30s → 60s)
- Fixed release.yml sed pattern for settings.py (`pb_version: str =` format)
- Fixed double-publish risk by removing tag trigger from docker-build.yml

### Operator Action Required

> ⚠️ **For existing multi-node deployments**: This release changes how telemetry flows.
> - No action required for new deployments
> - Existing secondaries will automatically start sending metrics to primary
> - Query logs already shipped to primary; this is now accurately documented

### Upgrade Instructions

```bash
# Pull and restart
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d

# Or pin to this version
POWERBLOCKADE_VERSION=v0.6.0 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=v0.6.0 docker compose -f docker-compose.ghcr.yml up -d
```

---

## [0.5.8] - 2025-02-20

> **Release Type**: Patch Release
> **Upgrade Safety**: ✅ Safe upgrade, no manual steps required

### Fixed

- RPZ zone file generation improvements
- Cache warming reliability

### Upgrade Instructions

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

---

## Release Format Reference

Each release should follow this format:

```markdown
## [X.Y.Z] - YYYY-MM-DD

> **Release Type**: Patch | Feature | Major
> **Upgrade Safety**: Safe | See Operator Action Required

### Added
- New features

### Changed
- Changes to existing functionality
- Mark BREAKING changes explicitly

### Fixed
- Bug fixes

### Operator Action Required
(Only for feature/major releases with breaking changes)
> ⚠️ **Description of what operators need to do**

### Upgrade Instructions
```bash
# Standard upgrade commands
```
```

---

## Version Compatibility

| Version Range | Safe to Upgrade? | Notes |
|---------------|------------------|-------|
| 0.5.x → 0.5.y | ✅ Always | Patch releases are always safe |
| 0.5.x → 0.6.0 | ⚠️ Check docs | Feature release, may require config updates |
| 0.x.y → 1.0.0 | ⚠️ Read migration guide | Major release, breaking changes possible |

See [Release Policy](docs/RELEASE_POLICY.md) for complete details.
