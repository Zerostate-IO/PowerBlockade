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

### 0.0.1 (MVP usable)
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

### 0.1.0 (polish)
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

### 0.2.x (observability)
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

### 1.0.0 (stabilize via feedback)
Focus: “feature requests converge; defaults solid; stable upgrades”.

Likely scope:
- Privacy controls (log retention, anonymization options)
- Advanced search options
- Better performance modes and tuning
- Optional external search backend (OpenSearch) only if repeatedly requested

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
