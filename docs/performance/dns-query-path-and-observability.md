# DNS53 Query Path and Observability Control Points

This document traces the end-to-end query flow through the PowerBlockade DNS stack, identifying each hop, cache layer, policy enforcement point, and observability extraction point.

---

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              POWERBLOCKADE DNS53 QUERY PATH                                      │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                  │
│   ┌────────────┐    ┌──────────────┐    ┌───────────────┐    ┌─────────────────────────────┐   │
│   │   CLIENT   │───>│   dnsdist    │───>│   recursor    │───>│   UPSTREAM DNS (internet)   │   │
│   │  (LAN IP)  │    │ (edge proxy) │    │  (resolver)   │    │                             │   │
│   └────────────┘    └──────────────┘    └───────────────┘    └─────────────────────────────┘   │
│         │                  │                     │                                               │
│         │                  ▼                     │                                               │
│         │           ┌──────────────┐            │                                               │
│         │           │  PACKET      │            │                                               │
│         │           │  CACHE       │            │                                               │
│         │           │  (500k)      │            │                                               │
│         │           └──────────────┘            │                                               │
│         │                                     │                                               │
│         │                                     ▼                                               │
│         │                              ┌───────────────┐                                      │
│         │                              │  RPZ POLICY   │                                      │
│         │                              │  (blocking)   │                                      │
│         │                              └───────────────┘                                      │
│         │                                     │                                               │
│         │                                     ▼                                               │
│         │                              ┌───────────────┐                                      │
│         │                              │ RECORD CACHE  │                                      │
│         │                              │   (2M) +      │                                      │
│         │                              │ PACKET CACHE  │                                      │
│         │                              │   (1M)        │                                      │
│         │                              └───────────────┘                                      │
│         │                                                                                  │
│         ▼                            (on response)                                           │
│   ┌────────────┐                     ┌───────────────┐                                      │
│   │  RESPONSE  │<────────────────────│   DNSTAP      │                                      │
│   │  TO CLIENT │                     │   EMISSION    │                                      │
│   └────────────┘                     └───────────────┘                                      │
│                                              │                                               │
│                                              ▼                                               │
│                                     ┌───────────────────┐                                    │
│                                     │ dnstap-processor  │                                    │
│                                     │  (FrameStream)    │                                    │
│                                     └───────────────────┘                                    │
│                                              │                                               │
│                                              ▼                                               │
│                                     ┌───────────────────┐                                    │
│                                     │    admin-ui       │                                    │
│                                     │ /api/node-sync    │                                    │
│                                     │    /ingest        │                                    │
│                                     └───────────────────┘                                    │
│                                              │                                               │
│                                              ▼                                               │
│                                     ┌───────────────────┐                                    │
│                                     │    PostgreSQL     │                                    │
│                                     │ dns_query_events  │                                    │
│                                     └───────────────────┘                                    │
│                                              │                                               │
│                         ┌────────────────────┴────────────────────┐                           │
│                         ▼                                         ▼                           │
│                  ┌───────────────┐                      ┌───────────────────┐                  │
│                  │  ROLLUP       │                      │  PROMETHEUS       │                  │
│                  │  (hourly/daily)│                      │  /metrics         │                  │
│                  └───────────────┘                      └───────────────────┘                  │
│                                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Hop-by-Hop Sequence Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                        DNS QUERY FLOW (Text Sequence)                                           │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                                  │
│  PARTICIPANTS:                                                                                                   │
│    C  = LAN Client                                                                                               │
│    D  = dnsdist (edge)                                                                                           │
│    DC = dnsdist Cache (500k packet cache)                                                                        │
│    R  = Recursor                                                                                                 │
│    RPZ = RPZ Policy Engine                                                                                       │
│    RC = Recursor Cache (2M record + 1M packet)                                                                   │
│    U  = Upstream DNS                                                                                             │
│    DT = dnstap-processor                                                                                         │
│    API = admin-ui API                                                                                            │
│    PG = PostgreSQL                                                                                               │
│    PROM = Prometheus                                                                                             │
│                                                                                                                  │
│  FLOW:                                                                                                           │
│                                                                                                                  │
│  1. C -> D: DNS Query (UDP/TCP :53)                                                                              │
│     └─ Note: ACL check at dnsdist.conf.template:17-25                                                            │
│                                                                                                                  │
│  2. D -> DC: Check packet cache                                                                                  │
│     └─ Note: dnsdist.conf.template:40-48 (500k entries, 24h TTL)                                                 │
│                                                                                                                  │
│  3. IF cache HIT:                                                                                                │
│     3a. DC --> D: Cached response                                                                                │
│     3b. D --> C: Response (no recursor hit)                                                                       │n│     └─ Note: Query flow complete, skip to step 11                                                                │
│                                                                                                                  │
│  4. ELSE cache MISS:                                                                                             │
│     4a. D -> R: Forward to recursor:5300                                                                          │
│         └─ Note: dnsdist.conf.template:31-37 (4 sockets, firstAvailable)                                        │
│                                                                                                                  │
│  5. R -> RPZ: Check RPZ policy                                                                                   │
│     └─ Note: rpz.lua:6-14 (whitelist first, then blocklist)                                                      │
│                                                                                                                  │
│  6. IF RPZ BLOCK:                                                                                                │
│     6a. RPZ --> R: NXDOMAIN                                                                                      │
│     6b. R --> D: Blocked response                                                                                 │
│     └─ Note: Jump to step 10                                                                                     │
│                                                                                                                  │
│  7. ELSE RPZ ALLOW:                                                                                              │
│     7a. R -> RC: Check record/packet cache                                                                       │
│         └─ Note: recursor.conf.template:16-20 (2M + 1M entries)                                                  │
│                                                                                                                  │
│  8. IF recursor cache HIT:                                                                                       │
│     8a. RC --> R: Cached answer                                                                                   │
│                                                                                                                  │
│  9. ELSE recursor cache MISS:                                                                                    │
│     9a. R -> U: Recursive resolution                                                                              │
│     9b. U --> R: Authoritative answer                                                                             │
│     9c. R -> RC: Store in cache                                                                                   │
│                                                                                                                  │
│  10. R --> D: DNS response                                                                                        │
│      └─ Note: Return to dnsdist                                                                                  │
│                                                                                                                  │
│  11. D -> DC: Store in packet cache (if miss)                                                                     │
│      └─ Note: For future queries                                                                                 │
│                                                                                                                  │
│  12. D --> C: Response to client                                                                                  │
│                                                                                                                  │
│  13. D -> DT: DNSTap emission (CLIENT_RESPONSE only)                                                              │
│      └─ Note: dnsdist.conf.template:63-65 (response-only design)                                                 │
│      └─ Note: FrameStream TCP to dnstap-processor:6000                                                           │
│                                                                                                                  │
│  14. DT: Parse dnstap, extract client_ip, qname, qtype, rcode, latency                                            │
│      └─ Note: main.go:446-490 (CLIENT_RESPONSE only)                                                             │
│      └─ Note: main.go:129-143 (load RPZ for blocked detection)                                                   │
│      └─ Note: main.go:341 (buffer if needed)                                                                     │
│                                                                                                                  │
│  15. DT -> API: POST /api/node-sync/ingest                                                                        │
│      └─ Note: main.go:360 (batch up to 500 events)                                                               │
│      └─ Note: X-PowerBlockade-Node-Key header                                                                    │
│                                                                                                                  │
│  16. API: Validate events, upsert clients                                                                         │
│      └─ Note: node_sync.py:276-296 (IngestEvent model, client upsert)                                            │
│                                                                                                                  │
│  17. API -> PG: INSERT dns_query_events                                                                           │
│      └─ Note: node_sync.py:334-339 (ON CONFLICT DO NOTHING on event_id)                                          │
│                                                                                                                  │
│  PARALLEL METRICS PATH:                                                                                          │
│                                                                                                                  │
│  M1. R: Exposes /metrics endpoint                                                                                 │
│      └─ Note: recursor.conf.template:35-36 (Prometheus format)                                                   │
│                                                                                                                  │
│  M2. sync-agent: Scrapes recursor metrics                                                                         │
│      └─ Note: agent.py:75-112 (pdns_recursor_* metrics)                                                          │
│                                                                                                                  │
│  M3. sync-agent: Buffer metrics locally                                                                           │
│      └─ Note: agent.py:303,348-365 (SQLite, 7-day retention)                                                     │
│                                                                                                                  │
│  M4. sync-agent -> API: POST /api/node-sync/metrics                                                               │
│      └─ Note: agent.py:355 (buffered retry on failure)                                                           │
│                                                                                                                  │
│  M5. API -> PG: INSERT node_metrics                                                                               │
│      └─ Note: node_sync.py:387-408 (NodeMetrics model)                                                           │
│                                                                                                                  │
│  M6. API -> PROM: Expose /metrics endpoint                                                                        │
│      └─ Note: metrics.py:35-232 (powerblockade_* metrics)                                                        │
│                                                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Control Point Reference Table

| Step | Component | Effect | Source File:Line | Notes |
|------|-----------|--------|------------------|-------|
| **Ingress & ACL** | dnsdist | Accept/reject query by source IP | `dnsdist/dnsdist.conf.template:17-25` | ACLs for LAN ranges only |
| **Packet Cache Check** | dnsdist | Short-circuit if answer cached | `dnsdist/dnsdist.conf.template:40-48` | 500k entries, 24h TTL |
| **Stale Cache Serve** | dnsdist | Serve stale if upstream unavailable | `dnsdist/dnsdist.conf.template:49` | 60s stale TTL |
| **Backend Forward** | dnsdist | Route to recursor | `dnsdist/dnsdist.conf.template:31-37` | 4 sockets, firstAvailable policy |
| **RPZ Blocklist** | Recursor | Block matching domains | `recursor/rpz.lua:6-9` | Policy.NXDOMAIN |
| **RPZ Whitelist** | Recursor | Allow overrides | `recursor/rpz.lua:12-14` | Policy.PASSTHRU |
| **Record Cache** | Recursor | Cache recursive answers | `recursor/recursor.conf.template:16` | 2M entries |
| **Packet Cache** | Recursor | Cache complete responses | `recursor/recursor.conf.template:17-20` | 1M entries, 24h TTL |
| **DNSTap Emission** | dnsdist | Log response (not query) | `dnsdist/dnsdist.conf.template:63-65` | Response-only for Pi-hole-like logging |
| **FrameStream TCP** | dnsdist → dnstap-processor | Transport dnstap messages | `dnsdist/dnsdist.conf.template:56-62` | TCP logger to processor |
| **DNSTap Parse** | dnstap-processor | Extract client IP, qname, rcode | `dnstap-processor/cmd/dnstap-processor/main.go:446-490` | CLIENT_RESPONSE only |
| **Blocked Detection** | dnstap-processor | Match against RPZ sets | `dnstap-processor/cmd/dnstap-processor/main.go:129-143` | Reloads every 5s |
| **Event Buffer** | dnstap-processor | Store-and-forward on failure | `dnstap-processor/cmd/dnstap-processor/main.go:51-54` | BoltDB, 100MB/24h default |
| **Batch Ingest** | dnstap-processor → admin-ui | POST events to API | `dnstap-processor/cmd/dnstap-processor/main.go:360` | 500-event batches |
| **Event Upsert** | admin-ui | Insert with dedupe | `admin-ui/app/routers/node_sync.py:334-339` | event_id unique constraint |
| **Client Upsert** | admin-ui | Auto-create unknown IPs | `admin-ui/app/routers/node_sync.py:286-296` | Triggers PTR resolution |
| **Recursor Metrics** | sync-agent | Scrape /metrics endpoint | `sync-agent/agent.py:75-112` | pdns_recursor_* metrics |
| **Metrics Buffer** | sync-agent | 7-day store-and-forward | `sync-agent/agent.py:303,348-365` | SQLite buffer with max_age |
| **Metrics Push** | sync-agent → admin-ui | POST to /api/node-sync/metrics | `sync-agent/agent.py:355` | Buffered retry on failure |
| **Metrics Store** | admin-ui | Persist to node_metrics table | `admin-ui/app/routers/node_sync.py:387-408` | Per-node metrics history |
| **Prometheus Export** | admin-ui | Aggregate and expose | `admin-ui/app/routers/metrics.py:35-232` | powerblockade_* metrics |
| **Cache Flush (Primary)** | admin-ui | API call to recursor | `admin-ui/app/routers/blocking.py:183-197` | PUT /api/v1/servers/localhost/cache/flush |
| **Cache Flush (Secondary)** | admin-ui | Queue NodeCommand | `admin-ui/app/routers/blocking.py:199-204` | clear_cache command |
| **Secondary Flush Execute** | sync-agent | Poll and execute commands | `sync-agent/agent.py:196-234` | recursor cache flush via API |

---

## Cache Architecture Summary

### Two-Layer Design

```
┌─────────────────────────────────────────────────────────────────┐
│                    DNSDIST (Edge Layer)                         │
├─────────────────────────────────────────────────────────────────┤
│  Packet Cache: 500,000 entries                                  │
│  - Max TTL: 86400s (24h)                                        │
│  - Min TTL: 1s                                                  │
│  - Stale TTL: 60s (serve stale on upstream failure)             │
│  - Purpose: Eliminate recursor hits for repeated queries        │
│  Source: dnsdist/dnsdist.conf.template:40-49                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (cache miss)
┌─────────────────────────────────────────────────────────────────┐
│                    RECURSOR (Resolution Layer)                   │
├─────────────────────────────────────────────────────────────────┤
│  Record Cache: 2,000,000 entries                                │
│  - Stores authoritative answers                                 │
│  - Per-record TTL                                               │
│                                                                 │
│  Packet Cache: 1,000,000 entries                                │
│  - Max TTL: 86400s (24h)                                        │
│  - Negative TTL: 60s (NXDOMAIN)                                 │
│  - ServFail TTL: 5s                                             │
│                                                                 │
│  Purpose: Recursive resolution + answer caching                 │
│  Source: recursor/recursor.conf.template:16-20                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## DNSTap Response-Only Design

### Why Response-Only?

PowerBlockade logs only `CLIENT_RESPONSE` events from dnsdist, not `CLIENT_QUERY` events.

**Rationale** (from `dnsdist/dnsdist.conf.template:63-64`):
- One row per answered query/qtype (Pi-hole-like experience)
- Avoids duplicate entries (query + response for same transaction)
- Latency is only available in response events
- RCODE is only available in response events

**Tradeoff**:
- No record of queries that never receive a response (timeouts, drops)
- Could be addressed with query-timeout fallback if needed

**Implementation**:
```
File: dnstap-processor/cmd/dnstap-processor/main.go:446-448

if t != dnstap.Message_CLIENT_RESPONSE {
    continue
}
```

### Client IP Attribution

The dnstap `CLIENT_RESPONSE` message contains:
- **QueryAddress**: The actual downstream client IP (LAN device)
- **ResponseAddress**: The dnsdist bind address (internal)

PowerBlockade uses `QueryAddress` for client attribution:
```
File: dnstap-processor/cmd/dnstap-processor/main.go:450-455

ipBytes := msg.GetQueryAddress()
ip := net.IP(ipBytes)
if ip == nil {
    continue
}
clientIP := ip.String()
```

---

## RPZ Enforcement Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    RPZ POLICY ENFORCEMENT                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Query arrives at Recursor                                      │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ Load RPZ files (on startup/reload)      │                   │
│  │ Source: recursor/rpz.lua:6-14           │                   │
│  └─────────────────────────────────────────┘                   │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ Check whitelist.rpz first               │                   │
│  │ defpol = Policy.PASSTHRU                │                   │
│  │ → Allowed, skip blocklist               │                   │
│  └─────────────────────────────────────────┘                   │
│       │ (not in whitelist)                                       │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ Check blocklist-combined.rpz            │                   │
│  │ defpol = Policy.NXDOMAIN                │                   │
│  │ → Blocked, return NXDOMAIN              │                   │
│  └─────────────────────────────────────────┘                   │
│       │ (not blocked)                                           │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ Proceed to normal resolution            │                   │
│  │ (cache check or upstream query)         │                   │
│  └─────────────────────────────────────────┘                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Blocked Detection at Ingest**:
The dnstap-processor independently checks RPZ files to mark events as blocked:
```
File: dnstap-processor/cmd/dnstap-processor/main.go:129-143

loadSets() // Reload RPZ files (every 5s max)
_, allow := allowSet[normQName]
_, blocked := blockedSet[normQName]
isBlocked := blocked && !allow
```

---

## Metrics Flow

### Recursor Metrics Scrape (sync-agent)

```
File: sync-agent/agent.py:75-112

def scrape_recursor_metrics(recursor_url: str) -> dict:
    r = requests.get(f"{recursor_url}/metrics", timeout=5)
    # Parses pdns_recursor_* metrics:
    # - cache_hits, cache_misses, cache_entries
    # - packetcache_hits, packetcache_misses
    # - answers_0_1, answers_1_10, answers_10_100, answers_100_1000, answers_slow
    # - concurrent_queries, outgoing_timeouts
    # - servfail_answers, nxdomain_answers
    # - questions, all_outqueries, uptime
```

### Metrics Push with Buffering (sync-agent)

```
File: sync-agent/agent.py:346-365

metrics = scrape_recursor_metrics(recursor_url)
if metrics:
    metrics_buffer.put(metrics, time.time())  # Buffer locally

pending = metrics_buffer.peek(limit=50)
if pending:
    for item_id, item_metrics in pending:
        r = post("/api/node-sync/metrics", item_metrics)
        if r.status_code < 300:
            ids_to_delete.append(item_id)
        else:
            break  # Stop on failure, keep buffered
    metrics_buffer.delete(ids_to_delete)
```

### Metrics Ingest (admin-ui)

```
File: admin-ui/app/routers/node_sync.py:377-410

@router.post("/metrics")
def metrics(payload: MetricsRequest, node: Node, db: Session):
    metric = NodeMetrics(
        node_id=node.id,
        cache_hits=payload.cache_hits,
        cache_misses=payload.cache_misses,
        # ... all fields
    )
    db.add(metric)
    db.commit()
```

### Prometheus Export (admin-ui)

```
File: admin-ui/app/routers/metrics.py:35-232

@router.get("/metrics")
def metrics(db: Session):
    # Aggregates from dns_query_events (24h window):
    # - powerblockade_queries_total
    # - powerblockade_blocked_total
    # - powerblockade_cache_hits_total (latency < 5ms proxy)
    # - powerblockade_block_rate
    # - powerblockade_cache_hit_rate
    # - powerblockade_qps
    
    # Per-node metrics from node_metrics table:
    # - powerblockade_recursor_cache_hits{node="..."}
    # - powerblockade_recursor_cache_misses{node="..."}
    # - powerblockade_recursor_cache_entries{node="..."}
    # - powerblockade_recursor_answers_latency{node="...",le="..."}
    # - etc.
```

---

## Cache Flush Operations

### Primary Node Flush

```
File: admin-ui/app/routers/blocking.py:174-217

@router.post("/clear-cache")
def clear_cache(request: Request, db: Session):
    # 1. Flush primary recursor via HTTP API
    recursor_url = settings.recursor_api_url.rstrip("/")
    resp = client.put(
        f"{recursor_url}/api/v1/servers/localhost/cache/flush",
        headers={"X-API-Key": os.environ.get("RECURSOR_API_KEY", "")},
        params={"domain": "."}  # Flush all
    )
    
    # 2. Queue clear_cache command for secondaries
    secondary_nodes = db.query(Node).filter(
        Node.status == "active", 
        Node.name != "primary"
    ).all()
    for node in secondary_nodes:
        cmd = NodeCommand(node_id=node.id, command="clear_cache")
        db.add(cmd)
    db.commit()
```

### Secondary Node Flush Execution

```
File: sync-agent/agent.py:196-234

def poll_and_execute_commands(primary_url, headers, recursor_url, api_key):
    r = requests.get(f"{primary_url}/api/node-sync/commands", ...)
    commands = data.get("commands", [])
    
    for cmd in commands:
        if cmd_type == "clear_cache":
            success, result = clear_recursor_cache(recursor_url, api_key)
            # Then report result back to primary

def clear_recursor_cache(recursor_url, api_key):
    r = requests.put(
        f"{recursor_url}/api/v1/servers/localhost/cache/flush",
        headers={"X-API-Key": api_key},
        params={"domain": "."},
        timeout=10,
    )
```

---

## Event Ingest Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    EVENT INGEST PIPELINE                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  dnstap-processor                                               │
│       │                                                         │
│       │ Batch events (max 500)                                  │
│       │ Flush every 2s                                          │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ POST /api/node-sync/ingest              │                   │
│  │ X-PowerBlockade-Node-Key: <api_key>     │                   │
│  │ {"events": [...]}                       │                   │
│  │ Source: main.go:360                     │                   │
│  └─────────────────────────────────────────┘                   │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ Validate events (node_sync.py:276-281)  │                   │
│  │ Parse to IngestEvent model              │                   │
│  └─────────────────────────────────────────┘                   │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ Upsert clients (node_sync.py:286-296)   │                   │
│  │ Auto-create unknown IPs                 │                   │
│  └─────────────────────────────────────────┘                   │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ Build rows_data (node_sync.py:300-330)  │                   │
│  │ Normalize qname (lowercase, strip dot)  │                   │
│  │ Link client_id                          │                   │
│  └─────────────────────────────────────────┘                   │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ INSERT ... ON CONFLICT DO NOTHING       │                   │
│  │ (event_id unique constraint)            │                   │
│  │ Source: node_sync.py:334-339            │                   │
│  └─────────────────────────────────────────┘                   │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ Background PTR resolution               │                   │
│  │ For new clients only                    │                   │
│  │ Source: node_sync.py:348-352            │                   │
│  └─────────────────────────────────────────┘                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Event Deduplication

Events are deduplicated by `event_id`, a SHA-256 hash of:
```
node_name | timestamp | client_ip | qname | qtype | rcode
```

```
File: dnstap-processor/cmd/dnstap-processor/main.go:144-145

h := sha256.Sum256([]byte(fmt.Sprintf("%s|%s|%s|%s|%d|%d", 
    cfg.NodeName, ts.Format(time.RFC3339Nano), clientIP, normQName, qtype, rcode)))
eid := hex.EncodeToString(h[:])
```

The database constraint:
```
File: admin-ui/app/routers/node_sync.py:334-335

stmt = pg_insert(DNSQueryEvent).values(rows_data)
stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
```

---

## Secondary Node Sync Path

```
┌─────────────────────────────────────────────────────────────────┐
│                 SECONDARY NODE SYNC ARCHITECTURE                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Secondary Node                          Primary Node           │
│  ┌─────────────────┐                   ┌─────────────────┐     │
│  │  sync-agent     │                   │    admin-ui     │     │
│  └────────┬────────┘                   └────────┬────────┘     │
│           │                                     │               │
│           │ 1. Register                         │               │
│           │────────────────────────────────────>│               │
│           │    POST /api/node-sync/register     │               │
│           │                                     │               │
│           │ 2. Heartbeat (every 60s)            │               │
│           │────────────────────────────────────>│               │
│           │    POST /api/node-sync/heartbeat    │               │
│           │<────────────────────────────────────│               │
│           │    {"config_version": "..."}        │               │
│           │                                     │               │
│           │ 3. Config Sync (on version change)  │               │
│           │────────────────────────────────────>│               │
│           │    GET /api/node-sync/config        │               │
│           │<────────────────────────────────────│               │
│           │    RPZ files, forward zones, settings               │
│           │                                     │               │
│           │ 4. Events Ingest                    │               │
│           │────────────────────────────────────>│               │
│           │    POST /api/node-sync/ingest       │               │
│           │                                     │               │
│           │ 5. Metrics Push                     │               │
│           │────────────────────────────────────>│               │
│           │    POST /api/node-sync/metrics      │               │
│           │                                     │               │
│           │ 6. Command Poll                     │               │
│           │────────────────────────────────────>│               │
│           │    GET /api/node-sync/commands      │               │
│           │<────────────────────────────────────│               │
│           │    [{"command": "clear_cache",...}] │               │
│           │                                     │               │
│           │ 7. Execute & Report                 │               │
│           │    (execute clear_cache locally)    │               │
│           │────────────────────────────────────>│               │
│           │    POST /api/node-sync/commands/result              │
│           │                                     │               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Key sync-agent behaviors**:
- Config sync triggered by `config_version` change in heartbeat response
- RPZ files written only if checksum differs
- Forward zones written to `/etc/pdns-recursor/forward-zones.conf`
- Metrics buffered in SQLite with 7-day retention (`METRICS_BUFFER_MAX_AGE=604800`)

---

## Traffic Attribution Policy

### Network Boundary Definitions

| Boundary | CIDR | Source | Purpose |
|----------|------|--------|---------|
| Docker Internal Subnet | `172.30.0.0/24` (default) | `compose.yaml:312` via `DOCKER_SUBNET` | Container-to-container traffic within the PowerBlockade stack |
| RFC 1918 Private | `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` | `dnsdist.conf.template:17-20` | Legitimate LAN client queries |
| CGNAT | `100.64.0.0/10` | `dnsdist.conf.template:21` | Carrier-grade NAT clients |
| Link Local | `169.254.0.0/16`, `fe80::/10` | `dnsdist.conf.template:22,25` | Auto-configuration traffic |

**Key Distinction**: The Docker internal subnet (`172.30.0.0/24` by default) is the boundary between internal service traffic and external client queries. This is NOT the same as RFC 1918 private ranges which represent legitimate downstream clients.

### Classification Rules

Classification is determined by matching `client_ip` against network boundaries in the following **precedence order**:

```
Rule 1: Docker Internal Subnet (EXCLUDE)
   IF client_ip ∈ DOCKER_SUBNET (default: 172.30.0.0/24)
   THEN classify as INTERNAL_CONTAINER

Rule 2: All Other IPs (INCLUDE)
   ELSE classify as EXTERNAL_CLIENT
```

### Default Exclusion Policy

| Classification | Persisted to DB | Included in Rollups | Shown in UI | Included in Metrics |
|----------------|-----------------|---------------------|-------------|---------------------|
| `INTERNAL_CONTAINER` | **NO** | **NO** | **NO** | **NO** |
| `EXTERNAL_CLIENT` | **YES** | **YES** | **YES** | **YES** |

### Filter Application Points

| Layer | Location | Implementation | Impact |
|-------|----------|----------------|--------|
| **Ingest** | `admin-ui/app/routers/node_sync.py:314` | Filter rows_data before INSERT | Reduces DB storage, never stores internal queries |
| **Rollup** | `admin-ui/app/services/rollups.py` | Filter during aggregation | Rollups exclude internal traffic |
| **Display** | Analytics routers | WHERE clause in queries | UI never shows internal queries |
| **Metrics** | `admin-ui/app/routers/metrics.py:35` | Exclude from Prometheus exports | Metrics reflect only external traffic |

---

## Buffering and Resilience

### dnstap-processor Buffer

```
File: dnstap-processor/cmd/dnstap-processor/main.go:51-54

buf, err := buffer.Open(cfg.Buffer.Path, cfg.Buffer.MaxBytes, cfg.Buffer.MaxAge)
// Default: 100MB max, 24h max age
// Events deleted only after successful ingest POST
```

### sync-agent Metrics Buffer

```
File: sync-agent/agent.py:287-288,303

buffer_path = os.getenv("METRICS_BUFFER_PATH", "/var/lib/powerblockade/metrics.db")
buffer_max_age = int(os.getenv("METRICS_BUFFER_MAX_AGE", "604800"))  # 7 days

metrics_buffer = MetricsBuffer(buffer_path, max_age_seconds=buffer_max_age)
```

**Difference in resilience**:
- DNS events: buffered/retried (BoltDB, bounded by size/age)
- Metrics: buffered/retried (SQLite, 7-day retention)
- Heartbeat: fire-and-forget (logged on failure, not queued)

---

## File Reference Summary

| Component | Config File | Key Lines |
|-----------|------------|-----------|
| dnsdist | `dnsdist/dnsdist.conf.template` | ACL:17-25, Cache:40-49, Backend:31-37, DNSTap:56-65 |
| recursor | `recursor/recursor.conf.template` | Cache:16-20, RPZ:23, API:29-33 |
| RPZ policy | `recursor/rpz.lua` | Blocklist:6-9, Whitelist:12-14 |
| dnstap-processor | `dnstap-processor/cmd/dnstap-processor/main.go` | Parse:446-490, Buffer:51-54, Ingest:360 |
| sync-agent | `sync-agent/agent.py` | Metrics scrape:75-112, Buffer:303, Commands:196-234 |
| admin-ui ingest | `admin-ui/app/routers/node_sync.py` | Ingest:269-354, Metrics:377-410 |
| admin-ui metrics | `admin-ui/app/routers/metrics.py` | Export:35-232 |
| cache flush | `admin-ui/app/routers/blocking.py` | Flush:174-217 |
|| admin-ui rollups | `admin-ui/app/services/rollups.py` | Hourly:18-82, Daily:85-148 |

---

## Filter Placement Matrix

### Multi-Layer Internal Traffic Exclusion

Internal traffic (Docker subnet `172.30.0.0/24` by default) must be excluded from analytics to prevent observability contamination. This section defines where filtering is applied, why each layer matters, and how to verify consistency.

**Design Principle**: Defense in depth with explicit consistency checks. Filtering at multiple layers ensures no single point of failure corrupts analytics.

### Layer-by-Layer Placement

| Layer | Location | Action | Rationale | Failure Risk |
|-------|----------|--------|-----------|--------------|
| **1. Ingest Tagging** | `admin-ui/app/routers/node_sync.py:314` | Add `is_internal` boolean to rows_data before INSERT; evaluate against `DOCKER_SUBNET` | Single source of truth; downstream layers inherit classification; efficient storage-level filtering | Misconfigured `DOCKER_SUBNET` causes incorrect classification; schema migration required |
| **2. Rollup Filtering** | `admin-ui/app/services/rollups.py:38` | Add `DNSQueryEvent.is_internal.is_(False)` filter to aggregation queries | Ensures rollups reflect only external traffic; provides statistical consistency checkpoint | If ingest tagging is wrong, rollups silently inherit error; needs separate validation |
| **3. Metrics Export** | `admin-ui/app/routers/metrics.py:40-47` | Add `DNSQueryEvent.is_internal.is_(False)` to Prometheus metric queries | Prometheus metrics drive alerting; must reflect external traffic only | If ingest fails, metrics still show contaminated data; Grafana dashboards show wrong values |
| **4. Dashboard Display** | Analytics routers (`clients.py`, `domains.py`, etc.) | Add `is_internal.is_(False)` to WHERE clauses | Safety net for direct queries; ensures UI never shows internal IPs | Multiple query points to maintain; easy to miss a router |

### Implementation Details

#### Layer 1: Ingest Tagging

```python
# File: admin-ui/app/routers/node_sync.py
# After line 296 (after db.flush()), before rows_data construction:

import ipaddress
from app.settings import settings  # Assuming DOCKER_SUBNET in settings

def is_internal_ip(ip_str: str, docker_subnet: str) -> bool:
    try:
        network = ipaddress.ip_network(docker_subnet, strict=False)
        return ipaddress.ip_address(ip_str) in network
    except ValueError:
        return False  # Invalid IP treated as external

# In ingest loop:
docker_subnet = settings.docker_subnet  # e.g., "172.30.0.0/24"
for ev in parsed:
    # ... existing ts parsing ...
    is_internal = is_internal_ip(ev.client_ip, docker_subnet)
    rows_data.append({
        # ... existing fields ...
        "is_internal": is_internal,  # New field
    })
```

**Schema Migration Required**:
```sql
ALTER TABLE dns_query_events ADD COLUMN is_internal BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX idx_dns_query_events_internal ON dns_query_events(is_internal);
```

#### Layer 2: Rollup Filtering

```python
# File: admin-ui/app/services/rollups.py:38
# Add filter to exclude internal traffic:

results = (
    db.query(...)
    .filter(
        DNSQueryEvent.ts >= hour_start,
        DNSQueryEvent.ts < hour_end,
        DNSQueryEvent.is_internal.is_(False),  # NEW
    )
    .group_by(...)
    .all()
)
```

#### Layer 3: Metrics Export

```python
# File: admin-ui/app/routers/metrics.py:40-47
# Add filter to Prometheus exports:

total = (
    db.query(sa.func.count(DNSQueryEvent.id))
    .filter(
        DNSQueryEvent.ts >= since,
        DNSQueryEvent.is_internal.is_(False),  # NEW
    )
    .scalar() or 0
)

blocked = (
    db.query(sa.func.count(DNSQueryEvent.id))
    .filter(
        DNSQueryEvent.ts >= since,
        DNSQueryEvent.blocked.is_(True),
        DNSQueryEvent.is_internal.is_(False),  # NEW
    )
    .scalar() or 0
)
```

#### Layer 4: Dashboard Display

```python
# File: admin-ui/app/routers/analytics/*.py
# Add filter to all query log retrievals:

queries = (
    db.query(DNSQueryEvent)
    .filter(
        DNSQueryEvent.ts >= cutoff,
        DNSQueryEvent.is_internal.is_(False),  # NEW: All display queries
    )
    .order_by(DNSQueryEvent.ts.desc())
    .limit(limit)
    .all()
)
```

### Consistency Checks

To verify filtering is working correctly at all layers, implement these validation queries:

#### Check 1: Ingest Tagging Accuracy

```sql
-- Verify internal IPs are tagged correctly
SELECT client_ip, is_internal, COUNT(*) as cnt
FROM dns_query_events
WHERE ts > NOW() - INTERVAL '1 hour'
GROUP BY client_ip, is_internal
HAVING (is_internal = true) != (client_ip << '172.30.0.0/24'::inet)
-- Should return 0 rows
```

#### Check 2: Rollup-to-Raw Consistency

```sql
-- Compare raw external counts to rollup counts
WITH raw_external AS (
    SELECT COUNT(*) as cnt
    FROM dns_query_events
    WHERE ts >= date_trunc('hour', NOW() - INTERVAL '1 hour')
      AND ts < date_trunc('hour', NOW())
      AND is_internal = false
),
rollup_total AS (
    SELECT SUM(total_queries) as cnt
    FROM query_rollups
    WHERE bucket_start = date_trunc('hour', NOW() - INTERVAL '1 hour')
      AND granularity = 'hourly'
)
SELECT raw_external.cnt - COALESCE(rollup_total.cnt, 0) as diff
FROM raw_external, rollup_total;
-- Should be 0 or very small (timing differences)
```

#### Check 3: Metrics-to-Rollup Consistency

```sql
-- Compare Prometheus metric source to rollup totals
WITH metrics_source AS (
    SELECT COUNT(*) as cnt
    FROM dns_query_events
    WHERE ts >= NOW() - INTERVAL '24 hours'
      AND is_internal = false
),
rollup_24h AS (
    SELECT SUM(total_queries) as cnt
    FROM query_rollups
    WHERE bucket_start >= NOW() - INTERVAL '24 hours'
      AND granularity = 'hourly'
)
SELECT
    metrics_source.cnt as raw_count,
    rollup_24h.cnt as rollup_count,
    metrics_source.cnt - COALESCE(rollup_24h.cnt, 0) as diff
FROM metrics_source, rollup_24h;
-- Diff should be small; may differ due to rollup timing
```

#### Check 4: Display-to-Raw Consistency

```python
# Test in pytest or manual verification:
def test_display_excludes_internal(db, test_internal_ip):
    # Insert test event with internal IP
    internal_event = DNSQueryEvent(
        event_id="test-internal-1",
        ts=datetime.now(timezone.utc),
        client_ip=test_internal_ip,  # e.g., "172.30.0.5"
        qname="internal-test.example.com",
        is_internal=True,
    )
    db.add(internal_event)
    db.commit()

    # Query via analytics router
    response = client.get("/logs")
    assert "internal-test.example.com" not in response.text
```

### Tradeoffs Analysis

| Decision | Option A | Option B | Tradeoff |
|----------|----------|----------|----------|
| **Storage** | Tag + store internal events | Drop internal events at ingest | A: Auditability (can debug classification), higher storage. B: No internal data stored, can't retroactively fix classification bugs. **Recommend A** for production. |
| **Filter Timing** | Filter at ingest only | Filter at query time | A: Single point of change, faster queries. B: More flexible, but must remember to filter everywhere. **Recommend A with consistency checks**. |
| **Metrics Source** | Query dns_query_events directly | Query query_rollups table | A: Real-time, but expensive. B: Efficient, but stale by up to 1 hour. **Recommend B for dashboards, A for alerts**. |
| **Default Policy** | Exclude internal by default | Include internal by default | A: Safer (won't leak internal data). B: Explicit inclusion required. **Recommend A** (defense in depth). |
| **Consistency Check Frequency** | Every rollup run | Periodic batch job | A: Immediate detection, higher load. B: Lower load, delayed detection. **Recommend A for rollup consistency, B for cross-layer checks**. |

### Recommended Implementation Order

1. **Add schema migration** - `is_internal` column with index
2. **Implement ingest tagging** - Populate `is_internal` at insert
3. **Add rollup filter** - Modify `compute_hourly_rollup` and `compute_daily_rollup`
4. **Add metrics filter** - Modify Prometheus export queries
5. **Add display filter** - Modify all analytics routers
6. **Add consistency checks** - Implement validation queries as scheduled job
7. **Update Grafana dashboards** - Ensure dashboards use metrics (already filtered)

### Audit Trail for Classification

When debugging classification issues, these logs help:

```
# In node_sync.py ingest:
log.debug(f"Classified {ev.client_ip} as internal={is_internal}")

# In rollups.py:
internal_count = db.query(func.count(DNSQueryEvent.id)).filter(
    DNSQueryEvent.ts >= hour_start,
    DNSQueryEvent.ts < hour_end,
    DNSQueryEvent.is_internal.is_(True)
).scalar()
log.debug(f"Rollup {hour_start}: excluded {internal_count} internal events")
```

### Summary: Filter Placement Decision

**Primary filter at ingest** with `is_internal` tagging:
- Provides single source of truth
- Enables efficient storage-level queries
- Maintains auditability (can see internal events if needed)

**Secondary filters at rollup/metrics/display**:
- Defense in depth against coding errors
- Consistency checkpoints for validation
- Should be no-ops if ingest is correct

**Consistency checks between layers**:
- Verify ingest tagging accuracy
- Verify rollup-to-raw count alignment
- Verify metrics-to-rollup alignment
- Verify display-to-raw exclusion
