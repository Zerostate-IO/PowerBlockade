# PowerBlockade UI Improvements Sprint

**Created:** 2026-02-03  
**Environment:** Test hosts reachable via DNS over Netbird VPN (hostname only, not IP)  
**Test URL:** http://celsate:8080

---

## Executive Summary

| ID | Issue | Priority | Effort | Status |
|----|-------|----------|--------|--------|
| 1 | `/nodes` - Missing query/blocked stats | High | Medium | TODO |
| 2 | `/logs` - "Blocked" filter exists but unclear | Low | Low | TODO |
| 3 | `/blocked` - Missing features (filter, count, whitelist) | High | Medium | TODO |
| 4 | `/failures` - No failure aggregation | Medium | Medium | TODO |
| 5 | `/precache` - Stats show zeros + no secondary sync | High | Medium | TODO |
| 6 | `/setup` - PTR card not green when configured | Low | Trivial | TODO |
| 7 | **Consolidate log pages** | High | High | TODO |
| 8 | **Sync architecture improvements** | High | Medium | TODO |

---

## Part 1: Sync Architecture Analysis

### Current Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PRIMARY NODE                                    │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  admin-ui   │  │  PostgreSQL  │  │  recursor   │  │ dnstap-processor │  │
│  │  (FastAPI)  │  │  (database)  │  │  (DNS)      │  │ (event ingest)   │  │
│  └─────────────┘  └──────────────┘  └─────────────┘  └──────────────────┘  │
│         │                │                                    ▲              │
│         │ API            │ queries                           │ events       │
│         ▼                ▼                                    │              │
│  ┌─────────────────────────────────────────────────────────────┐            │
│  │                    /api/node-sync/*                          │            │
│  │  - /register, /heartbeat, /config, /ingest, /metrics, /commands         │
│  └─────────────────────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP (pull config, push events/metrics)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SECONDARY NODE (headless)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │ sync-agent  │  │  dnsdist    │  │  recursor   │  │ dnstap-processor │  │
│  │ (Python)    │  │  (proxy)    │  │  (DNS)      │  │ (ships to primary)│  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────────────┘  │
│        │                                  ▲                                  │
│        │ writes files                     │ DNS queries                      │
│        ▼                                  │                                  │
│  ┌─────────────────────────────────────────────────────────────┐            │
│  │  /etc/pdns-recursor/rpz/          (RPZ zone files)          │            │
│  │  /etc/pdns-recursor/forward-zones.conf                      │            │
│  └─────────────────────────────────────────────────────────────┘            │
│                                                                              │
│  NO DATABASE, NO ADMIN-UI, NO SCHEDULER                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### What Currently Syncs

| Data | Direction | Mechanism | Frequency |
|------|-----------|-----------|-----------|
| RPZ zone files | Primary → Secondary | sync-agent pulls `/api/node-sync/config` | Every 5 min or on change |
| Forward zones | Primary → Secondary | sync-agent pulls `/api/node-sync/config` | Every 5 min or on change |
| 2 settings only | Primary → Secondary | In `/api/node-sync/config` response | Every 5 min |
| DNS query events | Secondary → Primary | dnstap-processor POST `/api/node-sync/ingest` | Real-time batches |
| Recursor metrics | Secondary → Primary | sync-agent POST `/api/node-sync/metrics` | Every 60s |
| Commands (cache clear) | Primary → Secondary | sync-agent polls `/api/node-sync/commands` | Every 60s |

### Problems with Current Approach

1. **Ad-hoc settings sync** - Only 2 settings are synced; adding new features requires updating both `node_sync.py` AND `sync-agent.py`

2. **No state on secondaries** - Secondaries have no database, so features requiring local state (precache TTL tracking, query history) can't work

3. **No scheduler on secondaries** - Features like precache warming, periodic cleanup can't run on secondaries

4. **Tight coupling** - sync-agent knows specific file paths and formats; adding new config types requires code changes

### Design Principles for Secondary Nodes

Per user requirements:
> "Secondary nodes aren't for managing DNS (hence no UI) but should always strive to be a **full replica in function** of the primary, and **always feed back their data** to the primary."

This means:
- ✅ Same DNS behavior (blocking, forwarding, caching)
- ✅ Same precache warming behavior
- ✅ Same retention policies (though events live on primary)
- ✅ All telemetry flows back to primary
- ❌ No local management UI needed
- ❌ No local configuration changes

### Proposed Sync Architecture Improvements

#### Option A: Extend sync-agent (Recommended - Incremental)

Keep current architecture but make sync-agent smarter:

```
sync-agent v2:
├── Config sync (existing)
│   ├── RPZ files → /etc/pdns-recursor/rpz/
│   └── Forward zones → forward-zones.conf
├── Settings sync (NEW)
│   └── All settings → local JSON state file
├── Precache warming (NEW)
│   ├── Pull domain list from primary
│   └── Warm local recursor via DNS queries
└── Periodic tasks (NEW)
    └── Mini-scheduler for warming intervals
```

**Pros:**
- Minimal changes to existing architecture
- No new containers or dependencies
- Sync-agent already has access to recursor

**Cons:**
- sync-agent grows in complexity
- Local state in JSON file (not a real DB)

#### Option B: Add SQLite to sync-agent

Add a lightweight SQLite database to sync-agent for local state:

```python
# sync-agent with SQLite
- settings table (synced from primary)
- precache_entries table (local TTL tracking)
- Embedded scheduler for periodic jobs
```

**Pros:**
- Proper relational storage
- Can track precache TTL state across restarts
- Could enable future features needing local state

**Cons:**
- More complexity
- Another data store to manage

#### Option C: Full Settings Sync Protocol

Instead of ad-hoc settings, implement a generic protocol:

```python
# Primary returns ALL settings
GET /api/node-sync/config
{
    "settings": {
        "retention_events_days": "30",
        "ptr_resolution_enabled": "true",
        "precache_enabled": "true",
        "precache_domain_count": "1000",
        # ... all settings automatically
    }
}

# Sync-agent stores locally and acts on relevant ones
```

**Pros:**
- Future-proof - new settings sync automatically
- Single source of truth

**Cons:**
- Some settings may not apply to secondaries
- Need to categorize "syncable" vs "local-only" settings

### Recommended Approach: Option A + Option C Hybrid

1. **Sync ALL settings** via `/api/node-sync/config` (not just hand-picked ones)
2. **Extend sync-agent** with:
   - Local JSON state file for settings + precache state
   - Precache warming logic (using dnspython)
   - Simple interval-based scheduler (Python `threading.Timer`)
3. **New endpoint** `/api/node-sync/precache-domains` returns domain list for warming
4. **Categorize settings** with a `sync_to_nodes` flag in defaults

---

## Part 2: Detailed Issues and Fixes

### Issue 1: `/nodes` - Missing Query Statistics

**Root Cause:** `Node.queries_total` and `Node.queries_blocked` fields exist but are never populated. Data lives in `dns_query_events` table.

**Fix:** Compute aggregates on-demand in the nodes router:

```python
# routers/nodes.py
from sqlalchemy import func, cast, Integer

since = datetime.now(timezone.utc) - timedelta(hours=24)
stats = db.query(
    DNSQueryEvent.node_id,
    func.count().label('total'),
    func.sum(cast(DNSQueryEvent.blocked, Integer)).label('blocked')
).filter(DNSQueryEvent.ts >= since).group_by(DNSQueryEvent.node_id).all()

stats_by_node = {s.node_id: {'total': s.total or 0, 'blocked': s.blocked or 0} for s in stats}
```

---

### Issue 2: `/logs` - Blocked Filter

**Finding:** Filter EXISTS (Status dropdown with Blocked/Allowed options). Backend handles it correctly.

**Action:** Will be addressed as part of unified logs page consolidation.

---

### Issue 3: `/blocked` - Missing Features

**Missing:**
1. Blocklist filter dropdown
2. Block count aggregation
3. Whitelist action button

**Fix:** Part of unified logs page with:
- Blocklist dropdown populated from enabled blocklists
- "Top Blocked" tab with aggregated counts
- Whitelist button per row

---

### Issue 4: `/failures` - No Aggregation

**Missing:** Aggregated view showing which domains fail most often.

**Fix:** Part of unified logs page with "Top Failures" aggregation.

---

### Issue 5: `/precache` - Stats Show Zeros + No Secondary Sync

**Root Causes:**
1. In-memory cache starts empty on restart
2. Warming job waits 5 minutes before first run (no `next_run_time`)
3. Precache settings not synced to secondaries
4. Secondaries have no mechanism to run precache warming

**Fixes:**

A. **Primary - Immediate warming on boot:**
```python
# services/scheduler.py
_scheduler.add_job(
    precache_warming_job,
    IntervalTrigger(minutes=5),
    id="precache_warming",
    next_run_time=datetime.now(timezone.utc),  # Run immediately!
    replace_existing=True,
)
```

B. **Primary - Sync precache settings:**
```python
# routers/node_sync.py - in config() function
settings = {
    "retention_events_days": get_setting(db, "retention_events_days"),
    "ptr_resolution_enabled": get_setting(db, "ptr_resolution_enabled"),
    # Precache settings
    "precache_enabled": get_setting(db, "precache_enabled"),
    "precache_domain_count": get_setting(db, "precache_domain_count"),
    "precache_refresh_minutes": get_setting(db, "precache_refresh_minutes"),
    "precache_ignore_ttl": get_setting(db, "precache_ignore_ttl"),
    "precache_custom_refresh_minutes": get_setting(db, "precache_custom_refresh_minutes"),
}
```

C. **Primary - New endpoint for domain list:**
```python
# routers/node_sync.py
@router.get("/precache-domains")
def precache_domains(
    node: Node = Depends(get_node_from_api_key),
    db: Session = Depends(get_db),
):
    """Return top domains for precache warming on secondary nodes."""
    from app.models.settings import get_precache_enabled, get_precache_domain_count
    from app.services.precache import get_top_domains_to_warm
    
    enabled = get_precache_enabled(db)
    if not enabled:
        return {"ok": True, "enabled": False, "domains": []}
    
    domain_count = get_precache_domain_count(db)
    domains = get_top_domains_to_warm(db, hours=24, limit=domain_count)
    
    return {"ok": True, "enabled": True, "domains": domains}
```

D. **sync-agent - Add precache warming:**
```python
# sync-agent/agent.py - new functions
import dns.resolver

def warm_domain(domain: str, dns_server: str, port: int) -> bool:
    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = [dns_server]
        resolver.port = port
        resolver.lifetime = 5.0
        resolver.resolve(domain, "A")
        return True
    except:
        return False

def precache_warming(primary_url: str, headers: dict, dns_server: str, port: int):
    try:
        r = requests.get(f"{primary_url}/api/node-sync/precache-domains", headers=headers, timeout=30)
        if r.status_code != 200:
            return
        
        data = r.json()
        if not data.get("enabled"):
            return
        
        domains = data.get("domains", [])
        success = sum(1 for d in domains if warm_domain(d, dns_server, port))
        print(f"precache warming: {success}/{len(domains)} domains warmed")
    except Exception as e:
        print(f"precache warming error: {e}")
```

---

### Issue 6: `/setup` - PTR Card Not Green

**Root Cause:** Line 70 has hardcoded gray border instead of conditional.

**Fix:**
```html
<!-- Change line 70 from: -->
<div class="rounded-2xl border border-slate-800 bg-bg-800 p-5">

<!-- To: -->
<div class="rounded-2xl border {% if checklist.resolver_rules_configured %}border-emerald-700 bg-emerald-950/30{% else %}border-slate-800 bg-bg-800{% endif %} p-5">
```

---

### Issue 7: Consolidate Log Pages

Merge `/logs`, `/blocked`, `/failures` into single page with tabs.

**Implementation:** See detailed plan in original document section.

---

### Issue 8: Sync Architecture

Implement improved sync as described in Part 1.

---

## Implementation Todo List

### Phase 1: Quick Fixes

- [ ] **1.1** Fix PTR card border in `setup.html:70`
- [ ] **1.2** Add precache `next_run_time` for immediate boot warming in `scheduler.py`

### Phase 2: Node Stats

- [ ] **2.1** Add query aggregation to `routers/nodes.py`
- [ ] **2.2** Pass stats to template context
- [ ] **2.3** Update `nodes.html` to display aggregated stats

### Phase 3: Precache Sync (Primary Side)

- [ ] **3.1** Add precache settings to `/api/node-sync/config` response
- [ ] **3.2** Create `/api/node-sync/precache-domains` endpoint
- [ ] **3.3** Test endpoints manually

### Phase 4: Precache Sync (Secondary Side)

- [ ] **4.1** Add `dnspython` to `sync-agent/requirements.txt`
- [ ] **4.2** Add `warm_domain()` function to `sync-agent/agent.py`
- [ ] **4.3** Add `precache_warming()` function to sync-agent
- [ ] **4.4** Integrate precache warming into main loop (every 5 min)
- [ ] **4.5** Add local state file for tracking last warm time

### Phase 5: Unified Logs Page

- [ ] **5.1** Add view tabs to `logs.html` (All/Blocked/Failures/Top)
- [ ] **5.2** Handle `view` query parameter in `analytics.py`
- [ ] **5.3** Add whitelist button on blocked rows
- [ ] **5.4** Add blocklist filter dropdown
- [ ] **5.5** Add top domains aggregation view
- [ ] **5.6** Redirect `/blocked` → `/logs?view=blocked`
- [ ] **5.7** Redirect `/failures` → `/logs?view=failures`
- [ ] **5.8** Update navigation in `base.html`

### Phase 6: Testing

- [ ] **6.1** Test nodes page shows query counts
- [ ] **6.2** Test precache warms on primary boot
- [ ] **6.3** Test precache settings sync to secondary
- [ ] **6.4** Test secondary warms its local cache
- [ ] **6.5** Test unified logs page all views
- [ ] **6.6** Test whitelist button creates allow entry
- [ ] **6.7** Test setup page PTR card turns green

---

## Files Modified

```
admin-ui/app/
├── routers/
│   ├── analytics.py      # Unified logs, view param, aggregation
│   ├── nodes.py          # Query stats aggregation
│   └── node_sync.py      # Precache settings + domains endpoint
├── services/
│   └── scheduler.py      # next_run_time for precache
├── templates/
│   ├── base.html         # Navigation update
│   ├── logs.html         # Tabs, whitelist button, blocklist filter
│   └── setup.html        # PTR border fix

sync-agent/
├── agent.py              # Precache warming logic
└── requirements.txt      # Add dnspython
```
