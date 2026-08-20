# PowerBlockade Roadmap

This document is the **source of truth** for product direction and implementation sequencing.

## Product summary

PowerBlockade is a Pi-hole alternative for medium→advanced home users, built on a modern stack.

**Core user outcomes**
- Reliable DNS + caching
- Easy blocklists (presets + custom), enable/disable, scheduled updates
- Whitelist/blacklist
- Elegant modern **dark** UI
- Clear analytics: clients → domains, blocked, failures, health, precache benefit
- Seamless multi-node (secondary) join via generated compose + env

**Key constraints**
- No DHCP component.
- Must be deployable via **single docker compose + .env**.
- Must run on low-resource devices (rPi) but scale upward.

## Architecture decisions (locked)

### Storage
- **Postgres-only for now** for both config and query logs.
- OpenSearch is **not in scope** for MVP; may be optional later.

### Observability (v0.2.x)

#### Two Types of Metrics
1. **DNS Query Stats** (user-facing analytics)
   - Source: `dns_query_events` + `query_rollups` in Postgres
   - Displayed: Dashboard charts via ApexCharts
   - Data: Queries, blocks, clients, domains, response codes

2. **System Performance Metrics** (operational health)
   - Source: PowerDNS Recursor `/metrics` endpoint
   - Displayed: Grafana dashboards embedded in admin-ui
   - Data: Cache hit rates, latency distribution, upstream health, memory

#### Multi-Node Metrics Architecture (Push-Based)
```
Secondary Node                          Primary Node
┌─────────────────┐                    ┌─────────────────┐
│ sync-agent      │───metrics─────────▶│ admin-ui        │
│ (scrapes local  │   (POST)           │ /api/node-sync/ │
│  recursor:8082) │                    │   metrics       │ → Postgres
└─────────────────┘                    └─────────────────┘
                                              │
                                              ▼
                                       ┌─────────────────┐
                                       │ Prometheus      │
                                       │ (scrapes        │
                                       │  admin-ui only) │
                                       └────────┬────────┘
                                                │
                                                ▼
                                       ┌─────────────────┐
                                       │ Grafana         │
                                       │ (embedded in    │
                                       │  admin-ui)      │
                                       └─────────────────┘
```

**Why push-based (not Prometheus scrape)?**
- Works through NAT/firewalls (secondary→primary direction)
- Uses existing sync-agent connection
- No firewall rules needed on secondary
- Auto-discovered from registered nodes (no prometheus.yml edits)

**Junior-friendly deployment:**
```bash
# On secondary - that's it!
docker compose --profile sync-agent up -d
# sync-agent automatically pushes: events + config sync + metrics
```

#### Grafana Integration
- Grafana runs internal (no exposed port)
- Anonymous access enabled for embedding
- Kiosk mode for clean iframe embed
- Template variable `$node` for multi-node filtering/comparison
- Embedded in admin-ui `/system/health` page

### UI approach
- Admin UI is the primary interface.
- UI must be **modern, elegant, dark**.
- Near-real-time updates are sufficient (polling/htmx).
- Grafana dashboards embedded (not separate UI).

### Multi-node / HA
- Secondaries communicate with **Primary Admin UI API**.
- Secondaries do **not** connect directly to OpenSearch.
- Node join is initiated from UI:
  - user names node ("fred")
  - UI generates `.env` + `docker-compose.yml` bundle for that node

### Client naming (no DHCP)
- Provide **subnet-based** client name resolution rules.
- Use upstream resolver(s) **only for client name resolution** (PTR), not for all DNS.
- MVP uses **PTR-only** + manual overrides.

### Domain overrides (forward zones)
- Support domain → upstream servers (1+)
- Support **global** rules (apply to all nodes) and **per-node** overrides.
- Resolution precedence: most specific per-node override → most specific global → normal recursion.

## Releases

> **Status as of 0.10.0 (2026-08-20):** the original 0.0.1 / 0.1.0 / 0.2.x scope
> below is **shipped**, along with performance/observability work beyond it —
> measured warm-path p99 0.147 ms @ 99.9% edge hit ratio, native sub-ms
> observability on five services, pair-based warming with boot burst, and a
> fail-closed benchmark harness with committed artifacts. Current release: 0.10.0.

### Release philosophy on the road to 1.0

We are **not** rushing to 1.0 — expect a long 0.x runway (think Netbird's
0.7x cadence): steady feature releases that each stand alone, with quality
gates unchanged. Version 1.0 is not "feature complete," it is a **stability
contract**: bulletproof upgrades, tested backup/restore, security close-out,
and docs we'd hand a stranger. Features keep shipping in 1.x after it.

### Historical scope (shipped)

#### 0.0.1 (MVP usable)
Focus: “works for home users; analytics present; not fully polished”.

Must-have:
- Postgres schema for:
  - users, nodes
  - blocklists + manual entries
  - clients + client name resolver rules
  - forward zones (global + per-node)
  - query events + rollups
  - config versions + retention
- Ingest pipeline:
  - recursor events → primary API → Postgres
  - secondaries → primary API → Postgres
- Admin UI pages (dark, modern):
  - Dashboard (QPS, blocked%, cache, failures)
  - Clients (who asked what)
  - Domains (who/what is failing)
  - Blocked (by client/domain/list)
  - Failures (SERVFAIL/NXDOMAIN trends)
  - Precache (status + benefit)
  - Blocklists + Whitelist/Blacklist + Apply
  - Forward zones (global + node-scoped)
  - Nodes (generate package, status)
- In-app guides:
  - first-run setup checklist
  - contextual “what is this” help on key pages

#### 0.1.0 (polish)
Focus: "fast, friendly, resilient, batteries included".

Must-have:
- Better UX polish and information architecture
- Background jobs:
  - scheduled blocklist updates
  - retention jobs
  - precache scheduling
- Better filtering/search UX (without heavy indexing)
- Diagnostics/health UI (clear warnings; actionable remediation)
- Robust node config sync (config versioning + pull/apply + reload)

#### 0.2.x (observability)
Focus: "unified system health view; multi-node comparison".

Must-have:
- Push-based metrics collection from secondary nodes
- `node_metrics` table for storing pushed metrics
- `/api/node-sync/metrics` endpoint for sync-agent
- admin-ui `/metrics` aggregates all nodes with labels
- Grafana embedded in admin-ui (anonymous + kiosk mode)
- System Health page with node selector/comparison
- Prometheus + Grafana internal-only (no exposed ports)

Nice-to-have:
- Alerting thresholds (Prometheus alertmanager)
- Container metrics (cAdvisor)
- Historical trends export

### 1.0.0 (the stability contract)
Focus: “you can run this on your family's network and not fear upgrades”.

Must-have (tracked as Work Order O):
- CI-proven upgrade path from every recent 0.x minor (real stacks, real data)
- First-class backup/restore of all state, with tested restores
- Security close-out: login rate limiting, admin-action audit, session
  hardening, optional TOTP 2FA; secondary ACL tightening; dead-file removal
- Privacy controls (per-class retention, client-IP anonymization,
  per-client logging opt-out)
- Docs sweep: this roadmap, PROJECT.md package depictions, upgrade guides

Feature work (Work Orders J-P) lands in 0.x releases along the way; 1.0 is
the release where the promises get notarized, not where the features stop.

## Work orders (implementation sequencing)

### Work Order A: Postgres logging backend
- Event schema (raw + rollups)
- Partitioning + retention strategy
- Ingest endpoint writes to Postgres + updates rollups

### Work Order B: UI analytics (reads Postgres + Prometheus)
- Chart endpoints and tables
- Near-real-time updates (polling/htmx)
- Dark design system + components

### Work Order C: Blocking + config apply loop
- Blocklist ingest + RPZ generator
- Manual entries
- Apply + reload

### Work Order D: Client naming
- Subnet-based resolver rules
- PTR-only background resolver + caching
- Manual overrides

### Work Order E: Forward zones
- Global + per-node models
- UI with “apply globally” toggle + per-node selection
- Sync to nodes + reload

### Work Order F: Multi-node hardening
- sync-agent config pull/apply
- node health reporting
- config version roll-forward

### Work Order G: Observability stack (v0.2.x)
- `node_metrics` Postgres table + migration
- `/api/node-sync/metrics` ingest endpoint
- sync-agent metrics push (scrape local recursor, POST to primary)
- admin-ui `/metrics` with multi-node labels
- Grafana anonymous + embedding config
- PowerBlockade Grafana dashboard (node variable, key panels)
- System Health page in admin-ui (iframe embed)
- Remove Prometheus/Grafana external ports

### Work Order H: Deployment profiles — light mode / performance mode (planned)
Supersedes the earlier "replace Prometheus+Grafana with VictoriaMetrics" plan
(issue #40). Decision (2026-08-20): **both, via compose profiles** — the full
stack stays default; a light profile trades it down for small hosts.

- `performance` (default): dnsdist + recursor with full caches, Prometheus +
  Grafana with the DNS Performance dashboard, prober, alerting
- `light`: VictoriaMetrics single-node (Prometheus-compatible scraping,
  ~50-150 MB) in place of Prometheus+Grafana (~300-600 MB saved); vmalert for
  rules; admin-ui's native Postgres-backed analytics remain the primary UI;
  smaller cache defaults sized from occupancy data
- Cache sizing per profile informed by `docs/performance/experiment-log.md`
  right-sizing findings; document the memory/visibility trade on each
- Keep the sub-ms latency histogram working in BOTH profiles (it is the
  headline observability feature; VictoriaMetrics scrapes it unchanged)

Tracked as issue #40 (metrics stack evaluation, revised).

### Work Order I: Multi-flow saturation benchmark (post-0.10.0, planned)
Publish a server-limited throughput number to match the class of public
benchmarks (AdGuard Home's OxiDNS figures use up to 256 outstanding
queries; our committed 8,497 QPS baseline is single-flow and explicitly
flow-limited — a 4-flow supplemental run already hit 13,841 QPS with no
config change):

- Multi-flow dnsperf campaign (1/4/16/64/256 flows) on production-class
  hardware, cold and warm, via the existing harness
- Publish methodology + artifacts in `docs/performance/results/` and
  update `docs/comparisons.md`'s throughput table from a measured ceiling
  instead of the "floor, not ceiling" caveat

## Work orders toward 1.0 (added 2026-08-20, after the 0.10.0 release)

Priority-ordered backlog for the 0.x runway. Each becomes one or more
releases; ordering below is sequencing guidance, not a fixed schedule.

### Work Order J: Encrypted DNS listeners (high priority, 1.0-blocking)
DoH, DoT, and optionally DoQ/QUIC terminations on the dnsdist edge — the
single biggest switch-blocker vs AdGuard Home (see docs/comparisons.md):
- dnsdist native DoH/DoT/DoQ listeners + certificate plumbing (ACME via the
  existing traefik profile or standalone; renewal story documented)
- Admin UI toggle + per-listener settings; secondaries get encrypted
  listeners in their generated packages
- Benchmark impact measured (added latency of TLS handshakes vs the 0.147 ms
  warm-path p99 baseline) and documented in the comparisons page
- Flips the worst row in the comparisons "gives up" table

### Work Order K: Sync engine + secondary deployment hardening (high)
The 0.10.0 bowlister deployment exposed the weak seam: extraction modes,
ownership, stale node rows, config-sync failure modes:
- End-to-end vetting of the secondary lifecycle: generate → deploy →
  register → sync → upgrade → re-generate; scripted in CI, not by hand
- Fix zip extraction ergonomics (modes/ownership preserved or install
  script that repairs them); `pb` CLI subcommand for node bootstrap
- Sync-agent failure taxonomy + recovery: config drift detection,
  resync-from-scratch, node key rotation, orphaned-node cleanup UX
- Load-test the ingest path (multi-secondary, burst buffering behavior)

### Work Order L: UI and dashboard overhaul (high)
"It works but it is not pretty, and it doesn't tell you how well things
are running":
- Design pass on the admin UI (information architecture, typography,
  spacing, mobile)
- System-health surfaces rebuilt around native metrics: cache hit ratios,
  sub-ms latency percentiles, warming/boot-burst state, node fleet health
  as first-class dashboard widgets — the numbers exist; the UI must show them
- Live/near-real-time polish (htmx polling coherence, sensible refresh rates)

### Work Order M: Automation & AI-agent API (medium)
Token-authenticated REST surface for machines, not just browsers:
- Scoped API tokens (read-only metrics/analytics vs write-capable
  block/unblock, whitelist, flush-cache, node actions)
- Documented, versioned OpenAPI spec; stable enough for scripts and for
  AI agents (MCP server as a thin adapter over it is a natural follow-on)
- Rate limits + full audit logging on every mutating call
- Use case: "ask your AI why dns queries are slow / unblock example.com"

### Work Order N: Privacy controls (medium, 1.0-blocking per old 1.0 sketch)
- Per-data-class retention knobs (events, rollups, metrics, audit)
- Client-IP anonymization/truncation modes for the privacy-forward
- Per-client logging opt-out honored across primary and secondaries

### Work Order O: Stability contract work (1.0-blocking)
- CI upgrade-path tests: spin up each recent 0.x minor with seeded data,
  upgrade, assert integrity (extends the release runtime gate)
- Backup/restore: one-command full export (config, zones, nodes, settings;
  query history optional) + tested restore + docs
- Security close-out: login rate limiting, session hardening, optional
  TOTP, admin-action audit surfacing, secondary DNS-level
  allow-from/addACL tightening, dead `recursor/recursor.conf` removal
- Docs debt sweep: PROJECT.md stale package depictions, roadmap history

### Work Order P: Per-client / group policies (medium)
RPZ selection per client group (kids VLAN vs adult VLAN parity with
Pi-hole groups / AGH per-client settings):
- Client groups model + UI; per-group blocklist sets + manual overrides
- dnsdist/recursor rule wiring; sync to secondaries; analytics segmented
  by group

### Work Order Q: DHCP — parked flex, deliberately out of core
Stance (2026-08-20): DHCP stays OUT of core PowerBlockade — different
failure domain, router dnsmasq/Kea pairs fine beside us. Parked idea for a
far-future flex: **optional DHCP with multi-node failover** (primary +
secondaries cooperating on lease state), purely as a "nobody else does
this at our quality bar" showcase. Do not schedule until J-P are done and
users ask for it.

Sequencing guidance: J (with I riding along) → K → L → H → M → N → P,
with O growing continuously in CI as each release ships. One work order
per release is a sane cadence; some pair naturally (L+H touch the same
surfaces; N+O share the privacy/security audit work).
