# Gap Analysis: Retention, Node Resilience, and Data Integrity

**Document Version**: 1.0  
**Date**: 2026-02-25  
**Status**: Complete

---

## Executive Summary

This document presents a comprehensive gap analysis of PowerBlockade's data persistence, retention behavior, and multi-node resilience. The analysis identified **21 actionable gaps** across 4 priority levels, with **2 critical issues** requiring immediate attention.

### Key Findings

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Data Retention | 1 | 1 | 2 | 0 | 4 |
| Node Lifecycle | 0 | 5 | 2 | 2 | 9 |
| Secondary Resilience | 0 | 1 | 1 | 1 | 3 |
| Scheduler/Concurrency | 1 | 0 | 1 | 0 | 2 |
| Upgrade/Rollback | 0 | 0 | 2 | 1 | 3 |
| **Total** | **2** | **7** | **8** | **4** | **21** |

### Immediate Actions Required

1. **P0-1**: Fix retention default inconsistency (`retention_node_metrics_days` returns 90 vs documented 365)
2. **P0-2**: Add distributed lock to scheduled jobs (prevent duplicate purges in multi-instance)

---

## 1. UI Data Truthfulness

### Summary

All UI components report real data from PostgreSQL. No mock or placeholder data was found in production paths.

### Data Flow Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Jinja2         │    │  FastAPI        │    │  SQLAlchemy     │
│  Templates      │───→│  Routers        │───→│  Models         │
│  (30 files)     │    │  (22 routers)   │    │  → PostgreSQL   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                                             │
         └──────────────── WebSocket /ws/stream ───────┘
                       (real-time updates)
```

### Verified Data Sources

| UI Component | Template | Router | Model | Source |
|-------------|----------|--------|-------|--------|
| Dashboard | `index.html` | `streaming.py` | Multiple | PostgreSQL |
| Blocks | `blocks.html` | `blocking.py` | `Block` | PostgreSQL |
| Nodes | `nodes.html` | `nodes.py` | `Node` | PostgreSQL |
| Queries | `queries.html` | `analytics.py` | `DNSQueryEvent` | PostgreSQL |
| Metrics | `metrics.html` | `metrics_dashboard.py` | `NodeMetrics` | PostgreSQL |
| Settings | `settings.html` | `settings.py` | `Settings` | PostgreSQL |

### Gaps Identified

| ID | Gap | Severity | Impact |
|----|-----|----------|--------|
| UI-1 | No "last updated" timestamps on dashboard cards | Medium | Users cannot detect stale data |
| UI-2 | No WebSocket reconnection with visual indicator | Medium | Silent data staleness |
| UI-3 | Inconsistent empty state handling | Low | User confusion |

---

## 2. Persistence and Retention

### Data Plane Inventory

| Plane | Technology | Retention Control | Default |
|-------|------------|-------------------|---------|
| Primary Data | PostgreSQL | Settings table | Varies |
| Query Logs | PostgreSQL | `retention_events_days` | 15 days |
| Node Metrics | PostgreSQL | `retention_node_metrics_days` | **90 or 365** |
| Rollups | PostgreSQL | `retention_rollups_days` | 90 days |
| Observability | Prometheus/Grafana | External config | Variable |
### Critical Gap: Retention Default Inconsistency

**Location**: `admin-ui/app/models/settings.py`

```python
# Constant definition
DEFAULTS = {
    "retention_node_metrics_days": 365,  # ← Documentation says 365
}

# Getter function
def get_retention_node_metrics_days(db: Session) -> int:
    return int(get_setting(db, "retention_node_metrics_days", 90))  # ← Returns 90!
```

**Impact**: Users expecting 365-day retention will have data purged at 90 days.

### Observability Data Persistence

| Data Type | Storage | Backup Status |
|-----------|---------|---------------|
| Prometheus metrics | Docker volume | Not in `pb backup` |
| Grafana dashboards | Docker volume | Not in `pb backup` |
| Alert config | Grafana DB | Not in `pb backup` |

**Note**: Observability volumes are not preserved during upgrades or rollbacks.
| RET-4 | No data archival before schema migration | Medium | Irreversible data loss |

---

## 2.5 Secondary Node Data Resilience

### Current Behavior

| Data Type | Buffered? | Storage | Max Retention | On Failure |
|-----------|----------|---------|---------------|------------|
| DNS query events | ✅ Yes | BoltDB | 100MB / 24h (rec: 7 days) | Queued until success or limit |
| Node metrics | ❌ No | None | — (req: 7 days) | Dropped immediately |
| Heartbeat | ❌ No | None | — | Dropped immediately |
### Implementation Details

**dnstap-processor** (Go):
- Uses BoltDB (`/var/lib/dnstap-processor/buffer.db`) for persistent buffering
- Default limits: 100MB max size, 24h max age (configurable)
- **Recommended for production**: Set `BUFFER_MAX_AGE=604800` (7 days)
- Events are only deleted after successful POST to `/api/node-sync/ingest`
- Retry every 2 seconds while buffer has pending events
- Code: `dnstap-processor/cmd/dnstap-processor/main.go:347-386`

**sync-agent** (Python):
- No buffering for metrics or heartbeat
- Metrics scraped from recursor and pushed immediately
- **Requirement**: Add 7-day persistent buffer (matching dnstap-processor pattern)
- Failed pushes are logged and data is dropped:
  ```python
  # sync-agent/agent.py:333-342
  metrics = scrape_recursor_metrics(recursor_url)
  if metrics:
      try:
          r = post("/api/node-sync/metrics", metrics)
      except Exception as e:
          print(f"metrics push error: {e}")  # ← Data lost
  ```

### Gaps Identified

| ID | Gap | Severity | Impact |
|----|-----|----------|--------|
| SEC-1 | sync-agent has no metrics buffering (7-day requirement) | High | Metrics lost during outages |
| SEC-2 | No disk-based queue for sync-agent | Medium | No recovery after prolonged outage |
| SEC-3 | Buffer size/age not configurable in UI | Low | Requires manual config editing |

## 3. Node Lifecycle and Resilience

### Current State Model (Insufficient)

```python
class NodeStatus(str, Enum):
    PENDING = "pending"  # Registered, awaiting first sync
    ACTIVE = "active"    # Syncing normally
    ERROR = "error"      # Sync failure detected
```

**Missing States**: `STALE`, `OFFLINE`, `QUARANTINE`

### Failure Mode Analysis

| Failure Mode | Current Behavior | Gap |
|--------------|------------------|-----|
| Node crashes | Status remains `ACTIVE` | No background detection |
| Network partition | Status remains `ACTIVE` | No stale/offline detection job |
| Long offline (>24h) | Returns to `ACTIVE` immediately | No quarantine |
| Version mismatch | Version stored but not validated | Silent corruption risk |
| Sync data corruption | No validation | Data integrity risk |

**Note**: Heartbeat mechanism EXISTS (`sync-agent/agent.py` sends every 60s, `admin-ui/app/routers/node_sync.py:93-112` receives). The gaps are:
1. No background job detects stale/offline nodes from `last_seen` field
2. Heartbeat blindly sets `status = "active"`, bypassing state machine
3. No version compatibility validation on heartbeat
### Recovery Path Analysis

```
Current Flow (Problematic):
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Node Offline │────→│ Returns     │────→│ Sync Resumes│
│ (days)       │     │ (no check)  │     │ Immediately │
└─────────────┘     └─────────────┘     └─────────────┘
                            │
                            └─── No validation
                            └─── No version check
                            └─── No data continuity check
```

### Gaps Identified

| ID | Gap | Severity | Impact |
|----|-----|----------|--------|
| NODE-1 | No `STALE`/`OFFLINE`/`QUARANTINE` states | High | Cannot triage unresponsive nodes |
| NODE-2 | No stale/offline detection job | High | Stale nodes appear healthy |
| NODE-3 | Heartbeat state machine bypassed | High | ERROR/QUARANTINE status cleared on heartbeat |
| NODE-4 | No version compatibility check | High | Data corruption risk |
| NODE-5 | No quarantine on long-offline return | High | Security/integrity risk |
| NODE-6 | No sync gap detection | Medium | Silent data loss |
| NODE-7 | No retry backoff | Low | Resource exhaustion |
---

## 4. Version Compatibility

### Current State

No version field exists in sync protocol. Master and slaves can run different versions with no warning.

### Proposed Compatibility Matrix

| Master | Slave | Compatibility | Behavior |
|--------|-------|---------------|----------|
| 2.0 | 2.0 | ✅ Full | Normal sync |
| 2.0 | 1.9 | ⚠️ Degraded | Sync with warnings |
| 2.0 | 1.0 | ❌ Incompatible | Reject sync |
| 1.0 | 2.0 | ❌ Incompatible | Reject sync |

### Gaps Identified

| ID | Gap | Severity | Impact |
|----|-----|----------|--------|
| VER-1 | No version field in sync protocol | High | Cannot detect skew |
| VER-2 | No compatibility matrix | High | Silent corruption |
| VER-3 | No version tracking in DB | Medium | Cannot audit history |

---

## 5. Scheduler and Concurrency

### Current State

APScheduler runs in-process with no distributed coordination.

```python
# admin-ui/app/main.py
def lifespan(_: FastAPI):
    start_scheduler()  # ← No distributed lock
```

### Problem: Multi-Instance Deployment

```
Instance A                    Instance B
┌──────────────────┐          ┌──────────────────┐
│ Scheduler        │  race    │ Scheduler        │
│ ├─ retention     │ ──────→  │ ├─ retention     │ = DUPLICATE
│ ├─ rollups       │ ──────→  │ ├─ rollups       │ = DUPLICATE
│ └─ blocklists    │ ──────→  │ └─ blocklists    │ = DUPLICATE
└──────────────────┘          └──────────────────┘
```

### Gaps Identified

| ID | Gap | Severity | Impact |
|----|-----|----------|--------|
| SCHED-1 | No distributed lock on jobs | **Critical** | Duplicate purges |
| SCHED-2 | No job overlap protection | Medium | Resource waste |

---

## 6. Upgrade and Rollback

### Upgrade Flow

```
pb update
├── 1. Backup database (pg_dump)
├── 2. Backup config (.env, RPZ)
├── 3. Pull new images
├── 4. Run migrations (alembic upgrade head)
├── 5. Restart services
├── 6. Verify health
└── 7. Save state
```

### Rollback Flow

```
pb rollback
├── 1. Read previous state
├── 2. Stop services
├── 3. Restore database [--fast skips]
├── 4. Start services
└── 5. Verify health
```

### Rollback Gaps

| Gap | Description | Severity |
|-----|-------------|----------|
| No observability restore | Grafana/Prometheus volumes not restored | Medium |
| No retention validation | No check that retention settings preserved | Medium |
| No sync position check | Node sync positions may be invalid | Low |

---

## 7. Remediation Backlog Summary

### Critical (Immediate)

| ID | Issue | Effort | Dependencies |
|----|-------|--------|--------------|
| P0-1 | Fix retention default inconsistency | 1 hour | None |
| P0-2 | Add distributed scheduler locks | 4 hours | None |

### High (Next Release)

| ID | Issue | Effort | Dependencies |
|----|-------|--------|--------------|
| P1-1 | Add missing node states | 1-2 days | None |
| P1-2 | Add stale/offline detection job | 1 day | P1-1 |
| P1-3 | Fix heartbeat state machine | 2 hours | P1-1 |
| P1-4 | Add version compatibility check | 1 day | P1-1 |
| P1-5 | Implement quarantine flow | 2 days | P1-1, P1-2 |
| P1-6 | Add metrics buffering to sync-agent | 1-2 days | None |

| ID | Issue | Effort | Dependencies |
|----|-------|--------|--------------|
| P2-1 | Add dashboard timestamps | 2 hours | None |
| P2-2 | WebSocket reconnection | 4 hours | None |
| P2-3 | Sync gap detection | 1 day | P1-3 |
| P2-4 | Pre-upgrade archival | 4 hours | None |
| P2-5 | Rollback observability restore | 1 day | None |
| P2-6 | Job execution metrics | 4 hours | P0-2 |

### Low (Backlog)

| ID | Issue | Effort | Dependencies |
|----|-------|--------|--------------|
| P3-1 | Consistent empty states | 2 hours | None |
| P3-2 | Sync retry backoff | 2 hours | None |
| P3-3 | Version health widget | 4 hours | P1-4 |
| P3-4 | Upgrade documentation | 2 hours | None |

---

## 8. Recommended Implementation Timeline

### Sprint 1 (Week 1-2)
- P0-1: Retention default fix
- P0-2: Distributed scheduler locks
- P1-1: Add missing node states
- P1-3: Fix heartbeat state machine
- P1-6: Metrics buffering for sync-agent

### Sprint 2 (Week 3-4)
- P1-2: Stale/offline detection job
- P1-4: Version compatibility check
- P2-1: Dashboard timestamps
- P2-2: WebSocket reconnection

### Sprint 3 (Week 5-6)
- P1-5: Quarantine flow
- P2-4: Pre-upgrade archival
- P2-6: Job execution metrics

### Sprint 4 (Week 7-8)
- P2-3: Sync gap detection
- P2-5: Rollback observability restoration
- P3 items as capacity allows

---

## Appendix A: Evidence Files

| File | Description |
|------|-------------|
| `.sisyphus/evidence/task-1-ui-truth-map.md` | UI data flow verification |
| `.sisyphus/evidence/task-2-persistence-inventory.md` | Data plane inventory |
| `.sisyphus/evidence/task-3-retention-upgrade-path.md` | Upgrade/rollback retention analysis |
| `.sisyphus/evidence/task-4-node-failure-matrix.md` | Node failure mode analysis |
| `.sisyphus/evidence/task-5-compatibility-matrix.md` | Version compatibility framework |
| `.sisyphus/evidence/task-6-node-lifecycle-contract.md` | Proposed state model |
| `.sisyphus/evidence/task-7-scheduler-ownership-guardrails.md` | Distributed lock implementation |
| `.sisyphus/evidence/task-8-prioritized-backlog.md` | Full remediation backlog |
| `.sisyphus/evidence/task-9-secondary-buffering.md` | Secondary node data buffering analysis |

---

## Appendix B: Key Code Locations

| Component | Location |
|-----------|----------|
| Settings/Defaults | `admin-ui/app/models/settings.py` |
| Retention Service | `admin-ui/app/services/retention.py` |
| Node Model | `admin-ui/app/models/node.py` |
| Node Sync API | `admin-ui/app/routers/node_sync.py` |
| Sync Agent | `sync-agent/agent.py` |
| Scheduler | `admin-ui/app/services/scheduler.py` |
| Upgrade CLI | `scripts/pb` |
| Migrations | `admin-ui/alembic/versions/` |
