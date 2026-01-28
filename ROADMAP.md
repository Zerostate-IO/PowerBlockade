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

### Metrics
- Prometheus scrapes:
  - PowerDNS Recursor `/metrics`
  - our services (ingest health, precache stats, node health)

### UI approach
- Admin UI is the primary interface.
- UI must be **modern, elegant, dark**.
- Near-real-time updates are sufficient (polling/htmx).

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
Focus: “fast, friendly, resilient, batteries included”.

Must-have:
- Better UX polish and information architecture
- Background jobs:
  - scheduled blocklist updates
  - retention jobs
  - precache scheduling
- Better filtering/search UX (without heavy indexing)
- Diagnostics/health UI (clear warnings; actionable remediation)
- Robust node config sync (config versioning + pull/apply + reload)

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
