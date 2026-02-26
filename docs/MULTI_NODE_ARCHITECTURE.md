# Multi-Node Architecture

> **Canonical Source of Truth** — This document is the authoritative reference for PowerBlockade multi-node behavior. All other documentation should reference this document rather than duplicating or contradicting its content.

## Overview

PowerBlockade supports a primary/secondary node architecture for high-availability DNS filtering. Secondary nodes synchronize configuration from the primary and forward telemetry data (query events and metrics) to the primary for centralized storage and analysis.

---

## Topology

```
                    ┌─────────────────────────────────┐
                    │           PRIMARY NODE          │
                    │                                 │
   ┌───────────────►│  ┌─────────┐    ┌───────────┐  │
   │                │  │ admin-ui│◄───│ Postgres  │  │
   │                │  │ (API)   │    │ (Storage) │  │
   │                │  └────┬────┘    └───────────┘  │
   │                │       │                        │
   │                │       ▼                        │
   │                │  ┌─────────┐                   │
   │                │  │ Grafana │                   │
   │                │  └─────────┘                   │
   │                └─────────────────────────────────┘
   │                                ▲
   │     Config Sync (GET /config)  │  Telemetry (POST /ingest, /metrics, /heartbeat)
   │                                │
   │                ┌───────────────┴───────────────┐
   │                │        SECONDARY NODE          │
   │                │                                │
   │                │  ┌──────────────┐              │
   └────────────────│  │ sync-agent   │──────────────┘
                    │  └──────┬───────┘
                    │         │
                    │         ▼
                    │  ┌──────────────────┐
                    │  │ dnstap-processor │
                    │  └──────────────────┘
                    │         │
                    │         ▼
                    │  ┌──────────────────┐
                    │  │ PowerDNS Recursor│
                    │  └──────────────────┘
                    └─────────────────────────────────
```

### Node Roles

| Role | Responsibilities |
|------|------------------|
| **Primary** | Stores all telemetry (query events, metrics), serves configuration to secondaries, runs admin UI, hosts Grafana dashboards |
| **Secondary** | Receives DNS queries, forwards telemetry to primary, syncs blocklists/forward-zones from primary |

---

## Data Flows

### 1. Query Events (Secondary → Primary)

DNS query events flow from secondary nodes to the primary for centralized storage and analysis.

**Flow:**
1. PowerDNS Recursor sends dnstap/protobuf events to `dnstap-processor`
2. `dnstap-processor` batches events and POSTs to primary's `/api/node-sync/ingest`
3. Primary stores events in `dns_query_events` table via `admin-ui`

**Code References:**
- Sender: `dnstap-processor/cmd/dnstap-processor/main.go` — POSTs to `/api/node-sync/ingest`
- Receiver: `admin-ui/app/routers/node_sync.py` — `ingest()` endpoint persists to `DNSQueryEvent` model

**Buffering:**
- dnstap-processor uses a local SQLite buffer (`/var/lib/dnstap-processor/buffer.db` by default)
- Events are buffered when the primary is unreachable and forwarded when connectivity resumes
- Configurable via `BUFFER_PATH`, `BUFFER_MAX_BYTES` (default: 100MB), `BUFFER_MAX_AGE` (default: 24h)

### 2. Node Metrics (Secondary → Primary)

Recursor performance metrics are scraped and forwarded to the primary.

**Flow:**
1. `sync-agent` scrapes Prometheus metrics from local PowerDNS Recursor
2. `sync-agent` POSTs metrics to primary's `/api/node-sync/metrics`
3. Primary stores metrics in `node_metrics` table

**Code References:**
- Sender: `sync-agent/agent.py` — `scrape_recursor_metrics()` and POST to `/api/node-sync/metrics`
- Receiver: `admin-ui/app/routers/node_sync.py` — `metrics()` endpoint persists to `NodeMetrics` model

**Buffering:**
- sync-agent uses a local SQLite buffer (`/var/lib/powerblockade/metrics.db` by default)
- Metrics are buffered when the primary is unreachable
- Configurable via `METRICS_BUFFER_PATH`, `METRICS_BUFFER_MAX_AGE` (default: 7 days)

### 3. Heartbeat (Secondary → Primary)

Secondary nodes send periodic heartbeats to indicate liveness.

**Flow:**
1. `sync-agent` sends heartbeat to primary's `/api/node-sync/heartbeat`
2. Primary updates `last_seen` and `last_heartbeat` timestamps

**Code References:**
- Sender: `sync-agent/agent.py` — POST to `/api/node-sync/heartbeat`
- Receiver: `admin-ui/app/routers/node_sync.py` — `heartbeat()` endpoint

### 4. Configuration Sync (Primary → Secondary)

Secondary nodes pull configuration from the primary.

**Flow:**
1. `sync-agent` GETs configuration from primary's `/api/node-sync/config`
2. Primary returns RPZ files, forward zones, and settings
3. Secondary writes files locally and triggers recursor reload

**Code References:**
- Provider: `admin-ui/app/routers/node_sync.py` — `config()` endpoint
- Consumer: `sync-agent/agent.py` — `sync_config()` function

**Triggers:**
- Periodic: Every `CONFIG_SYNC_INTERVAL_SECONDS` (default: 300 = 5 minutes)
- On-change: When `config_version` differs from last known version

---

## API Endpoints

| Endpoint | Direction | Purpose |
|----------|-----------|---------|
| `POST /api/node-sync/register` | Secondary → Primary | Node registration with name, version, IP |
| `POST /api/node-sync/heartbeat` | Secondary → Primary | Liveness signal and query counters |
| `GET /api/node-sync/config` | Secondary ← Primary | Pull RPZ files, forward zones, settings |
| `POST /api/node-sync/ingest` | Secondary → Primary | Batch DNS query event ingestion |
| `POST /api/node-sync/metrics` | Secondary → Primary | Recursor performance metrics |

**Authentication:** All endpoints require `X-PowerBlockade-Node-Key` header matching the node's `api_key`.

---

## What Stays Local vs. What Centralizes

### Centralized on Primary

| Data | Storage | Purpose |
|------|---------|---------|
| DNS query events | `dns_query_events` table | Historical query logs, analytics, troubleshooting |
| Node metrics | `node_metrics` table | Performance monitoring, capacity planning |
| Blocklists | `blocklists` table + RPZ files | Unified filtering rules |
| Forward zones | `forward_zones` table + config | DNS forwarding rules |
| Clients | `clients` table | Client IP tracking, PTR resolution |

### Local to Each Node

| Data | Location | Purpose |
|------|----------|---------|
| DNS cache | Recursor memory | Performance optimization |
| In-memory configuration | Recursor memory | Runtime state |
| Local buffers (when primary unreachable) | SQLite files | Temporary telemetry storage |

### Buffer Files (Secondary Nodes)

| Buffer | Path | Purpose |
|--------|------|---------|
| Query events | `/var/lib/dnstap-processor/buffer.db` | Persistent queue for events during primary outage |
| Metrics | `/var/lib/powerblockade/metrics.db` | Persistent queue for metrics during primary outage |

---

## Heartbeat and Stale Detection

### Heartbeat Interval

- **Default:** 60 seconds
- **Configuration:** `HEARTBEAT_INTERVAL_SECONDS` environment variable in `sync-agent`
- **Code:** `sync-agent/agent.py` — `interval = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "60"))`

### Stale/Offline Detection

The primary node uses time-based thresholds to detect offline secondaries:

- **Stale threshold:** When `last_heartbeat` exceeds the configured stale minutes (default: 5 minutes)
- **Status indicators:** UI shows warnings or "offline" status based on heartbeat freshness
- **Separate from interval:** The stale threshold is independent of heartbeat frequency; a node sending heartbeats every 60s will appear stale after ~5 missed heartbeats

---

## Environment Variables

### sync-agent (Secondary Node)

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_NAME` | *(required)* | Unique identifier for this node |
| `PRIMARY_URL` | *(required)* | URL of primary admin-ui (e.g., `http://primary-host:8080`) |
| `PRIMARY_API_KEY` | *(required)* | API key for authentication to primary |
| `HEARTBEAT_INTERVAL_SECONDS` | `60` | Seconds between heartbeats |
| `CONFIG_SYNC_INTERVAL_SECONDS` | `300` | Seconds between config syncs |
| `RECURSOR_API_URL` | `http://recursor:8082` | URL for local recursor API |
| `RPZ_DIR` | `/etc/pdns-recursor/rpz` | Directory for RPZ zone files |
| `FORWARD_ZONES_PATH` | `/etc/pdns-recursor/forward-zones.conf` | Forward zones config file |
| `METRICS_BUFFER_PATH` | `/var/lib/powerblockade/metrics.db` | Metrics buffer database |
| `METRICS_BUFFER_MAX_AGE` | `604800` (7 days) | Max age for buffered metrics |
| `DNS_SERVER` | `dnsdist` | DNS server for cache warming |

### dnstap-processor

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_NAME` | *(empty)* | Node identifier (optional on primary) |
| `PRIMARY_URL` | `http://admin-ui:8080` | URL of primary admin-ui |
| `PRIMARY_API_KEY` | *(required)* | API key for authentication |
| `BUFFER_PATH` | `/var/lib/dnstap-processor/buffer.db` | Event buffer database |
| `BUFFER_MAX_BYTES` | `100MB` | Maximum buffer size |
| `BUFFER_MAX_AGE` | `86400` (24h) | Max age for buffered events |

---

## Related Documentation

- [GETTING_STARTED.md](GETTING_STARTED.md) — Operator setup guide
- [UPGRADE_ROLLBACK_VALIDATION_PLAYBOOK.md](UPGRADE_ROLLBACK_VALIDATION_PLAYBOOK.md) — Upgrade procedures
- In-app help: `admin-ui/app/templates/help/multi-node.html`
