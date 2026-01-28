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

## Observability

### Design principles
- **Single UI**: All monitoring visible from admin-ui (no separate Grafana/Prometheus URLs).
- **Push-based metrics**: Secondary nodes push to primary (works through NAT).
- **Zero config for secondaries**: sync-agent handles everything automatically.

### Two categories of data

| Category | Source | Storage | Retention | Display |
|----------|--------|---------|-----------|---------|
| DNS Query Logs | dnstap → dnstap-processor | Postgres (`dns_query_events`) | 15 days (configurable) | Query log pages |
| DNS Aggregates | Computed from logs | Postgres (`query_rollups`) | 365 days | ApexCharts dashboard |
| System Performance | Recursor `/metrics` | Postgres (`node_metrics`) → Prometheus | 90 days | Grafana embedded |

### Retention strategy
- **Query logs**: Short retention (15 days default) - high volume, for debugging
- **Aggregates**: Long retention (365 days) - low volume, for trends
- **Node metrics**: Medium retention (90 days) - Prometheus also stores for dashboards
- All configurable via Settings page in admin-ui

### Multi-node metrics flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         PRIMARY NODE                             │
│                                                                  │
│  ┌──────────────┐    ┌────────────┐    ┌─────────────────────┐  │
│  │  Prometheus  │───▶│  Grafana   │◀───│   admin-ui          │  │
│  │  (internal)  │    │ (internal) │    │  /system/health     │  │
│  │              │    │ anonymous  │    │  (iframe embed)     │  │
│  └──────┬───────┘    │ + kiosk    │    └─────────────────────┘  │
│         │            └────────────┘                              │
│         │ scrapes admin-ui:8080/metrics                         │
│         ▼            (includes all nodes)                        │
│  ┌──────────────┐                                               │
│  │  admin-ui    │◀─── metrics push ───┐                         │
│  │  /api/node-  │                     │                         │
│  │  sync/metrics│                     │                         │
│  └──────────────┘                     │                         │
│         │                             │                         │
│         ▼                             │                         │
│  ┌──────────────┐              ┌──────┴───────┐                 │
│  │  Postgres    │              │  recursor    │ (local)         │
│  │ node_metrics │              │  :8082       │                 │
│  └──────────────┘              └──────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
                                        ▲
                                        │ metrics push
┌───────────────────────────────────────┼─────────────────────────┐
│                       SECONDARY NODE  │                          │
│                                       │                          │
│  ┌──────────────┐              ┌──────┴───────┐                 │
│  │  sync-agent  │─── scrapes ──│  recursor    │                 │
│  │              │   localhost  │  :8082       │                 │
│  │              │   :8082      └──────────────┘                 │
│  │              │                                                │
│  │  POSTs to primary:                                           │
│  │  - /api/node-sync/heartbeat (existing)                       │
│  │  - /api/node-sync/metrics   (new)                            │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
```

### Why push-based (not Prometheus scrape)?

| Concern | Pull (Prometheus scrapes secondaries) | Push (sync-agent posts to primary) |
|---------|---------------------------------------|-------------------------------------|
| NAT/firewall | ❌ Requires inbound port on secondary | ✅ Outbound only (existing connection) |
| Discovery | ❌ Manual prometheus.yml edits | ✅ Auto from registered nodes |
| Junior-friendly | ❌ Network config needed | ✅ Just run sync-agent |
| Latency | Real-time (15s scrape) | Near-real-time (60s push) |

For home deployments where secondaries may be behind NAT or firewalls, push-based is essential.

### Key recursor metrics to collect

| Metric | Purpose | Grafana Panel |
|--------|---------|---------------|
| `cache_hits`, `cache_misses` | Cache efficiency | Cache hit rate gauge |
| `answers0_1` through `answers_slow` | Latency distribution | Latency histogram |
| `concurrent_queries` | Current load | Load gauge |
| `outgoing_timeouts` | Upstream health | Error rate |
| `servfail_answers` | Resolution failures | Error trend |
| `packetcache_hits` | Packet cache benefit | Cache breakdown |

### Grafana configuration

```ini
# grafana.ini (or env vars)
[auth.anonymous]
enabled = true
org_name = Main Org.
org_role = Viewer

[security]
allow_embedding = true

[server]
root_url = ${GRAFANA_ROOT_URL:-http://localhost:8080/grafana/}
serve_from_sub_path = true
```

### Dashboard template variables

```json
{
  "templating": {
    "list": [
      {
        "name": "node",
        "type": "query",
        "query": "label_values(powerblockade_recursor_cache_hits, node)",
        "multi": true,
        "includeAll": true
      }
    ]
  }
}
```

### Admin-ui integration

The System Health page embeds Grafana in kiosk mode:

```html
<iframe 
  src="/grafana/d/powerblockade-health/system-health?orgId=1&kiosk=tv&theme=dark"
  class="w-full h-full border-0"
></iframe>
```

Grafana is proxied through admin-ui via `/grafana/*` route using httpx to avoid CORS issues and expose without additional ports. Grafana remains internal-only (expose: "3000").
