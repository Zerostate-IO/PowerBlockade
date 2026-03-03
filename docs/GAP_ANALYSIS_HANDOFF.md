# Gap Analysis: Executive Handoff

**Generated**: 2026-03-03  
**Status**: Ready for Execution  
**Owner**: Operations Team

---

## 1. Scope

This analysis examined four critical domains of PowerBlockade:

| Domain | Focus Areas | Gaps Found |
|--------|-------------|------------|
| **UI Data Truthfulness** | Dashboard accuracy, empty states, redirects | 3 |
| **Retention Durability** | Volume persistence, buffer durability, cleanup | 2 |
| **Upgrade/Rollback** | Pre-flight checks, migration safety, rollback validation | 2 |
| **Node Lifecycle** | State transitions, quarantine, version compatibility | 6 |

**Total Gaps Identified**: 17 items across P0-Critical to P3-Low severity

### What Was NOT Analyzed

- DNS resolution logic correctness
- RPZ zone content validation
- Network partition recovery (handled by sync-agent buffering)
- Frontend performance under load

---

## 2. Top 5 Risks

### P0-1: Advisory Lock Fallback Runs Job on Error

| Attribute | Value |
|-----------|-------|
| **Severity** | P0-Critical |
| **Impact** | Duplicate blocklist updates, double rollups, race conditions |
| **Location** | `admin-ui/app/services/scheduler.py:67` |
| **Fix** | Change fallback from `return func()` to `return None` |

**Why Critical**: The `run_with_advisory_lock` decorator runs the job anyway if lock acquisition fails. This defeats the entire purpose of the lock and could corrupt data in multi-replica scenarios.

### P0-2: sync-agent Metrics Buffer Not Persisted

| Attribute | Value |
|-----------|-------|
| **Severity** | P0-Critical |
| **Impact** | Up to 7 days of secondary node metrics lost on container recreation |
| **Location** | `compose.yaml` (sync-agent service) |
| **Fix** | Add volume `sync-agent-buffer:/var/lib/powerblockade` |

**Why Critical**: The sync-agent writes buffered metrics to `/var/lib/powerblockade/metrics.db` but no Docker volume maps this path. During upgrades, this data is silently lost.

### P1-3: Node State Transitions Not Implemented

| Attribute | Value |
|-----------|-------|
| **Severity** | P1-High |
| **Impact** | Stale nodes appear "active"; no accurate health visibility |
| **Location** | `admin-ui/app/routers/system.py:100-116` |
| **Fix** | Add periodic job to transition ACTIVE→STALE→OFFLINE |

**Why High**: Nodes never transition from ACTIVE to STALE/OFFLINE automatically. Health warnings exist but don't change status, leaving stale nodes appearing healthy.

### P1-4: Version Compatibility Checks Not Enforced

| Attribute | Value |
|-----------|-------|
| **Severity** | P1-High |
| **Impact** | Major version mismatch allows breaking config sync |
| **Location** | `admin-ui/app/routers/node_sync.py:83,107-108` |
| **Fix** | Implement `check_version_compatibility()` with BLOCK logic |

**Why High**: Major version mismatches should BLOCK config sync but currently proceed silently, potentially breaking secondary nodes.

### P1-5: Quarantine-on-Return Not Implemented

| Attribute | Value |
|-----------|-------|
| **Severity** | P1-High |
| **Impact** | Long-offline nodes resume without verification |
| **Location** | `admin-ui/app/routers/node_sync.py:84-108` |
| **Fix** | Check offline duration in heartbeat, set QUARANTINE if > 24h |

**Why High**: Nodes returning after 24+ hours offline should enter QUARANTINE for verification. Currently they resume active status immediately.

---

## 3. Critical Path

```
Phase 1: Data Safety (Week 1)
├── Rank 1: Fix advisory lock fallback     [P0]
└── Rank 2: Add sync-agent volume          [P0]
        │
Phase 2: Operational Safety (Week 2)
├── Rank 3: Implement state transitions    [P1] ←─ depends on nothing
│       │
│       ├── Rank 4: Add version enforcement     [P1] ←─ depends on Rank 3
│       │       │
│       │       └── Rank 5: Quarantine entry    [P1] ←─ depends on Ranks 3,4
│       │               │
│       │               └── Rank 16: Quarantine exit [P3] ←─ depends on Rank 5
│       │
│       └── Rank 7: Add configurable thresholds [P1] ←─ depends on Rank 3
│
├── Rank 6: Add locks to remaining jobs    [P1] ←─ depends on Rank 1
│
Phase 3: Resilience (Week 3+)
├── Rank 8: Event buffering for query history
├── Rank 9: Metrics unique constraint
├── Rank 10: Audit log retention
└── Ranks 11-17: UX improvements
```

**Minimum Path to Production Safety**: Ranks 1, 2, 3 (3 items, ~1 week)  
**Full Node Lifecycle Safety**: Ranks 1-5, 7 (6 items, ~2 weeks)

---

## 4. Immediate Actions

Execute in this order:

### Step 1: Fix Advisory Lock (Day 1)

```bash
# Verify current behavior
grep -A5 "except Exception" admin-ui/app/services/scheduler.py | head -10

# Fix: Change line ~67 from:
#     return func(*args, **kwargs)
# To:
#     return None

# Verify fix
cd admin-ui && python -m pytest tests/ -v
```

### Step 2: Add sync-agent Volume (Day 1)

```bash
# Add to compose.yaml under sync-agent service:
volumes:
  - sync-agent-buffer:/var/lib/powerblockade

# Add to volumes section:
volumes:
  sync-agent-buffer:

# Recreate container
docker compose -f docker-compose.ghcr.yml up -d sync-agent

# Verify volume exists
docker volume ls | grep sync-agent-buffer
```

### Step 3: Implement State Transitions (Days 2-3)

```bash
# Add periodic job to scheduler.py
# Check last_seen and update status to STALE/OFFLINE

# Add settings for thresholds
# health_offline_minutes = 30
# health_quarantine_threshold_minutes = 1440
```

### Step 4: Add Version Enforcement (Days 4-5)

```python
# In node_sync.py, add:
def check_version_compatibility(primary: str, secondary: str) -> tuple[str, str]:
    # Major mismatch = BLOCK
    # Minor mismatch = WARN
    # Patch mismatch = ALLOW
```

### Step 5: Implement Quarantine Entry (Days 5-7)

```python
# In heartbeat handler:
if node.status == "offline":
    offline_duration = now - node.last_seen
    if offline_duration > quarantine_threshold:
        node.status = "quarantine"
```

---

## 5. Deliverables Index

| Document | Purpose | Location |
|----------|---------|----------|
| **Gap Analysis Report** | Full findings and remediation | `docs/GAP_ANALYSIS_RETENTION_NODE_RESILIENCE.md` |
| **Validation Playbook** | Upgrade/rollback procedures | `docs/UPGRADE_ROLLBACK_VALIDATION_PLAYBOOK.md` |
| **Lifecycle Policy** | Node state machine and quarantine | `docs/NODE_LIFECYCLE_AND_QUARANTINE_POLICY.md` |
| **Remediation Backlog** | Prioritized 17-item list | `.sisyphus/evidence/task-8-remediation-backlog.md` |

### Evidence Files

| Task | Focus | File |
|------|-------|------|
| Task 1 | UI data sources and empty states | `.sisyphus/evidence/task-1-ui-truth-map.md` |
| Task 2 | Retention policies and volume gaps | `.sisyphus/evidence/task-2-persistence-inventory.md` |
| Task 3 | Pre/post upgrade verification | `.sisyphus/evidence/task-3-upgrade-retention-checks.md` |
| Task 4 | Failure modes and recovery | `.sisyphus/evidence/task-4-node-failure-matrix.md` |
| Task 5 | Version compatibility rules | `.sisyphus/evidence/task-5-compatibility-matrix.md` |
| Task 6 | State machine and transitions | `.sisyphus/evidence/task-6-lifecycle-contract.md` |
| Task 7 | Job scheduling and locks | `.sisyphus/evidence/task-7-scheduler-ownership.md` |

---

## 6. Assumptions and Defaults

### System Assumptions

| Assumption | Default | Rationale |
|------------|---------|-----------|
| Single admin-ui instance | 1 replica | Scheduler assumes single instance; scaling causes duplicate jobs |
| PostgreSQL persists data | Named volume `postgres-data` | Critical for data durability |
| Prometheus retention | 15 days | Configured via `.env`, not UI |
| Heartbeat interval | 60 seconds | sync-agent default |

### Threshold Defaults (Required but Missing)

| Setting | Default | Currently Implemented |
|---------|---------|----------------------|
| `health_stale_minutes` | 5 | Yes (warning only) |
| `health_offline_minutes` | 30 | No |
| `health_quarantine_threshold_minutes` | 1440 (24h) | No |

### Retention Defaults

| Table | Setting | Default |
|-------|---------|---------|
| `dns_query_events` | `retention_events_days` | 15 days |
| `query_rollups` | `retention_rollups_days` | 365 days |
| `node_metrics` | `retention_node_metrics_days` | 365 days |
| `config_changes` | None | No cleanup |

### Buffer Defaults

| Buffer | Max Size | Max Age | Persisted |
|--------|----------|---------|-----------|
| dnstap-processor | 100MB | 24h | Yes (named volume) |
| sync-agent metrics | Unlimited | 7 days | No (gap) |

### Version Compatibility Rules

| Skew | Status | Action |
|------|--------|--------|
| Patch (any) | ALLOW | None |
| Minor (±1) | WARN | Log warning |
| Major (any) | BLOCK | Halt sync, return 409 |

---

## 7. Quick Reference

### Verify P0 Fixes

```bash
# Rank 1: Lock fallback
grep -A5 "except Exception" admin-ui/app/services/scheduler.py | head -10
# Should show: return None (not return func)

# Rank 2: sync-agent volume
grep -A20 "sync-agent:" compose.yaml | grep -A5 "volumes:"
# Should show: sync-agent-buffer:/var/lib/powerblockade
```

### Run Full Test Suite

```bash
cd admin-ui && python -m pytest tests/ -v
```

### Check Node States

```bash
docker exec admin-ui psql -U postgres -d powerblockade -c \
  "SELECT name, status, last_seen FROM nodes ORDER BY last_seen DESC;"
```

---

## 8. Contact Points

For questions about specific findings:

| Domain | Primary Reference |
|--------|-------------------|
| UI/Evidence | `task-1-ui-truth-map.md` |
| Retention/Persistence | `task-2-persistence-inventory.md` |
| Upgrade Safety | `UPGRADE_ROLLBACK_VALIDATION_PLAYBOOK.md` |
| Node Lifecycle | `NODE_LIFECYCLE_AND_QUARANTINE_POLICY.md` |
| Prioritized Fixes | `task-8-remediation-backlog.md` |

---

*Document generated: 2026-03-03*  
*Analysis scope: PowerBlockade retention durability and node resilience*
