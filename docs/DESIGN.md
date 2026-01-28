# PowerBlockade Design Notes (Do Not Lose)

This document captures the design/UX/system decisions agreed during early planning.

## Guiding principles
- **Single compose + .env** should get a working system.
- **No DHCP** — integrate with the user’s existing gateway/firewall for naming.
- **Postgres-first** (lightweight, rPi-friendly). Avoid heavyweight search stacks by default.
- **Modern dark UI** with analytics first-class (not “minimal”).
- Prefer automation over manual steps; UI should generate what users need.

## UI/UX

### Look and feel
- Modern, elegant, dark.
- Near-real-time updates are fine.

### MVP analytics pages
Must support:
- Clients → what domains each client is querying
- Failures → what domains are failing and trends
- Blocked → what’s blocked, by client and domain, over time
- Precache benefit → show the value (hit rate uplift, warmed domains)

### In-app documentation
We will provide:
- First-run setup checklist (DNS pointing, admin creds, enabling blocklists)
- Contextual “what is this” help per page
- Health warnings with clear remediation

## DNS behavior

### Normal DNS resolution
- Recursor should do normal recursion and caching.
- Forwarding “everything to gateway” is **not** default.

### Domain overrides (forward zones)
- Domain → upstream server(s).
- Default is global (all nodes).
- UI supports per-node overrides:
  - checkbox “Apply to all nodes (global)” default true
  - if false, pick nodes to apply override

### Client name resolution (no DHCP)

#### Goal
Show friendly client names without running DHCP.

#### Rules
- Use subnet-based resolver rules.
- Only use internal resolver(s) for client naming; do not affect general outbound DNS.

#### MVP approach
- PTR-only lookups + caching + manual override.
- (Optional later) PTR validation via forward lookup.

## Storage

### Postgres-only (MVP)
- Config tables (blocklists, entries, forward zones, settings)
- Query event storage (partitioned) + rollups for dashboards
- Retention by dropping partitions

### Optional later
- OpenSearch only if requested, not required for MVP.

## Multi-node / HA

### Node join UX
- User creates node in UI: “name this node fred”.
- UI generates a package containing:
  - `.env`
  - `docker-compose.yml`
  - README instructions

### Data flow
- Secondaries send events to **primary API**.
- Primary stores events in Postgres.

### HA logging guarantees (planned)

**Primary is the source of truth for visibility.** The UI is designed to show a complete cross-node view by storing all events centrally on the primary.

#### Target behavior
- **Streaming ingest (not “sync-time logging”)**
  - Secondaries should POST events continuously (batched) to the primary ingest endpoint.
  - Config sync is separate from event ingest.

#### Edge cases we must handle
- **Primary unreachable / network partition**
  - Secondary must continue to serve DNS.
  - Secondary should buffer events locally (bounded disk spool) and replay when primary returns.
  - If spool is full, drop oldest first and surface clear warnings in UI.

- **Retries and duplicate delivery**
  - Ingest must be idempotent.
  - Each event should carry a stable `event_id` so the primary can dedupe on retry.

- **Clock skew**
  - Events are stored in UTC.
  - Small skew is tolerated; time-series uses server-side bucketing.
  - Recommend NTP on all nodes.

- **Backpressure / overload**
  - Secondary should batch and rate-limit sending.
  - Primary should accept batches efficiently and expose ingest health metrics.

#### Operational assumptions (common home HA)
- HA typically runs on 2 physical hosts on the same site/subnet.
- Even so, designs above should tolerate intermittent connectivity and reboots.

### Config sync
- Global config + per-node overrides must be supported.
- Nodes pull config bundles and reload recursor.
