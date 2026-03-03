# Execution Handoff: Retention Durability and Node Resilience

**Version**: 1.0
**Date**: 2026-03-03
**Package**: Full Gap Analysis - Retention, Node Resilience, and Upgrade Safety

---

## Executive Summary

### Scope

This handoff package addresses data integrity, operational safety, and multi-node reliability across four domains:

1. **UI Data Truthfulness** - Dashboard accuracy and empty-state handling
2. **Retention Durability** - Data persistence during outages and upgrades
3. **Upgrade/Rollback Coherence** - Safe version transitions with verification
4. **Node Lifecycle Management** - State transitions, quarantine, and compatibility

### Top 5 Critical Risks

| Rank | Risk | Severity | Impact | Fix Location |
|------|------|----------|--------|--------------|
| **1** | Advisory lock fallback runs job on error | P0 | Duplicate blocklist updates, double rollups | `scheduler.py:67` |
| **2** | sync-agent metrics buffer not persisted | P0 | 7 days metrics lost on container recreation | `compose.yaml` |
| **3** | Node state transitions not implemented | P1 | Stale nodes appear "active" | Periodic job needed |
| **4** | Version compatibility checks not enforced | P1 | Major version mismatch allows breaking sync | `node_sync.py` |
| **5** | Quarantine-on-return not implemented | P1 | Long-offline nodes resume without verification | `node_sync.py` |

### Critical Path

```
Week 1: Data Safety (Ranks 1-2)
├── Fix advisory lock fallback
└── Add sync-agent volume

Week 2: Operational Safety (Ranks 3-5, 7)
├── Implement state transitions
├── Add version enforcement
├── Implement quarantine-on-return
└── Add configurable thresholds

Week 3+: Resilience (Ranks 6, 8-17)
├── Add locks to remaining jobs
├── Event buffering, metrics constraints
└── UX improvements
```

### Recommended Execution Order

1. **Rank 1** first (no dependencies, highest risk)
2. **Rank 2** in parallel (no dependencies, easy fix)
3. **Rank 3** next (enables Ranks 4, 5, 7)
4. **Ranks 4-5** together (both depend on Rank 3)
5. **Remaining items** by priority

---

## Deliverables

### Primary Documents

| Document | Purpose | Location |
|----------|---------|----------|
| **Gap Analysis Report** | Consolidated findings, evidence citations, remediation path | `docs/GAP_ANALYSIS_RETENTION_NODE_RESILIENCE.md` |
| **Node Lifecycle Policy** | State machine, quarantine rules, compatibility gates | `docs/NODE_LIFECYCLE_AND_QUARANTINE_POLICY.md` |
| **Upgrade Playbook** | Pre/post-flight checks, rollback procedures | `docs/UPGRADE_ROLLBACK_VALIDATION_PLAYbook.md` |
| **Remediation Backlog** | 17 prioritized items with verification commands | `.sisyphus/evidence/task-8-remediation-backlog.md` |

### Evidence Files

| Task | Focus | Location |
|------|-------|----------|
| Task 1 | UI data sources and empty states | `.sisyphus/evidence/task-1-ui-truth-map.md` |
| Task 2 | Retention policies and volume gaps | `.sisyphus/evidence/task-2-persistence-inventory.md` |
| Task 3 | Pre/post upgrade verification | `.sisyphus/evidence/task-3-upgrade-retention-checks.md` |
| Task 4 | Failure modes and recovery | `.sisyphus/evidence/task-4-node-failure-matrix.md` |
| Task 5 | Version compatibility rules | `.sisyphus/evidence/task-5-compatibility-matrix.md` |
| Task 6 | State machine and transitions | `.sisyphus/evidence/task-6-lifecycle-contract.md` |
| Task 7 | Job scheduling and locks | `.sisyphus/evidence/task-7-scheduler-ownership.md` |

---

## Next Actions

### Immediate (P0 Items)

#### Rank 1: Fix Advisory Lock Fallback

**Location**: `admin-ui/app/services/scheduler.py`

**Current behavior** (line 67-68):
```python
except Exception:
    logger.warning(f"Could not acquire lock {lock_id}, running anyway")
    return func(*args, **kwargs)  # PROBLEM: runs job anyway
```

**Required change**:
```python
except Exception:
    logger.warning(f"Could not acquire lock {lock_id}, skipping job")
    return None  # Skip safely
```

**Verification**:
```bash
grep -A5 "except Exception" admin-ui/app/services/scheduler.py | head -10
```

#### Rank 2: Add sync-agent Volume

**Location**: `compose.yaml`

**Add to sync-agent service**:
```yaml
volumes:
  - sync-agent-buffer:/var/lib/powerblockade
```

**Add to volumes section**:
```yaml
volumes:
  sync-agent-buffer:
```

**Verification**:
```bash
grep -A20 "sync-agent:" compose.yaml | grep -A5 "volumes:"
```

### Short-term (P1 Items)

#### Rank 3: Implement State Transitions

Add periodic job to transition nodes based on `last_seen`:

```python
# In scheduler.py
@run_with_advisory_lock("node-state-transitions", 300)
def transition_node_states():
    stale_threshold = get_setting("health_stale_minutes", 5)
    offline_threshold = get_setting("health_offline_minutes", 30)
    
    # ACTIVE -> STALE
    db.execute("""
        UPDATE nodes SET status = 'stale'
        WHERE status = 'active'
        AND last_seen < NOW() - INTERVAL '1 minute' * %s
    """, [stale_threshold])
    
    # STALE -> OFFLINE
    db.execute("""
        UPDATE nodes SET status = 'offline'
        WHERE status = 'stale'
        AND last_seen < NOW() - INTERVAL '1 minute' * %s
    """, [offline_threshold])
```

#### Rank 4: Add Version Compatibility

**Location**: `admin-ui/app/routers/node_sync.py`

```python
def check_version_compatibility(primary: str, secondary: str) -> tuple[str, str]:
    """Returns (status, message) where status is ALLOW, WARN, or BLOCK."""
    if primary == "unknown" or secondary == "unknown":
        return ("WARN", "Unknown version, manual verification recommended")
    
    try:
        p_major, p_minor, _ = map(int, primary.split("."))
        s_major, s_minor, _ = map(int, secondary.split("."))
    except ValueError:
        return ("WARN", f"Unparseable version: {primary} vs {secondary}")
    
    if p_major != s_major:
        return ("BLOCK", f"Major version mismatch: {primary} vs {secondary}")
    
    if abs(p_minor - s_minor) > 1:
        return ("WARN", f"Minor version skew > 1: {primary} vs {secondary}")
    
    return ("ALLOW", f"Versions compatible: {primary} vs {secondary}")
```

#### Rank 5: Quarantine-on-Return

**Location**: `admin-ui/app/routers/node_sync.py` (heartbeat handler)

```python
# In heartbeat handler, before setting ACTIVE:
offline_duration = now - node.last_seen
quarantine_threshold = get_setting("health_quarantine_threshold_minutes", 1440)

if node.status == "offline" and offline_duration > timedelta(minutes=quarantine_threshold):
    node.status = "quarantine"
    node.quarantine_entry_time = now
    node.quarantine_reason = f"Returned after {offline_duration}"
    logger.warning(f"Node {node.name} quarantined after {offline_duration} offline")
else:
    node.status = "active"
```

### Long-term (P2 Items)

| Rank | Item | Effort |
|------|------|--------|
| 6 | Add locks to remaining 3 jobs | Low |
| 8 | Event buffering for query history | Medium |
| 9 | node_metrics unique constraint | Low |
| 10 | Audit log retention | Low |
| 11-17 | UX improvements | Low |

---

## Assumptions and Defaults

### Configuration Defaults

| Setting | Default | Notes |
|---------|---------|-------|
| `retention_events_days` | 15 | dns_query_events cleanup |
| `retention_rollups_days` | 365 | query_rollups cleanup |
| `retention_node_metrics_days` | 365 | node_metrics cleanup |
| `health_stale_minutes` | 5 | Warning threshold |
| `health_offline_minutes` | 30 | **NOT IMPLEMENTED** |
| `health_quarantine_threshold_minutes` | 1440 (24h) | **NOT IMPLEMENTED** |

### Operational Assumptions

1. **Single admin-ui instance** - Scheduler assumes one replica. Scaling requires external lock coordination.
2. **Primary/secondary topology** - Secondary nodes sync from single primary.
3. **Docker named volumes** - Persist across `docker compose down`.
4. **PostgreSQL-backed storage** - All state in database, not filesystem.

### Blast Radius by Component

| Component | Failure Mode | Recovery |
|-----------|--------------|----------|
| admin-ui | No UI access, jobs stop | DNS continues, no data loss |
| postgres | Complete outage | DNS continues until cache expires |
| dnstap-processor | Events buffered 24h | Replay on recovery |
| sync-agent | Metrics buffered 7d | Replay on recovery |
| dnsdist/recursor | DNS resolution fails | Service disruption |

---

## Verification Requirements

### Per-Fix Verification

#### Rank 1 (Lock Fallback)

```bash
# Before fix
grep -A3 "except Exception" admin-ui/app/services/scheduler.py
# Should show "running anyway"

# After fix
grep -A3 "except Exception" admin-ui/app/services/scheduler.py
# Should show "skipping job" and "return None"
```

#### Rank 2 (sync-agent Volume)

```bash
# Before fix
docker compose config | grep -A10 "sync-agent" | grep -A5 "volumes"
# Should show nothing for sync-agent

# After fix
docker compose config | grep -A10 "sync-agent" | grep -A5 "volumes"
# Should show sync-agent-buffer volume
```

#### Rank 3 (State Transitions)

```bash
# After implementation
docker exec admin-ui psql -U powerblockade -c "
  SELECT name, status, last_seen,
    EXTRACT(EPOCH FROM (NOW() - last_seen))/60 as minutes_stale
  FROM nodes
  WHERE status != 'active'
  ORDER BY last_seen DESC;"

# Force stale node for testing
docker exec admin-ui psql -U powerblockade -c "
  UPDATE nodes SET last_seen = NOW() - INTERVAL '10 minutes'
  WHERE name = 'test-node';"

# Run transition job manually
# Check status changed to 'stale'
```

#### Ranks 4-5 (Version/Quarantine)

```bash
# Test version blocking
curl -X POST http://localhost:8080/api/nodes/heartbeat \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"node_id": "test", "version": "99.0.0"}'
# Should return 409 Conflict for major mismatch

# Test quarantine entry
# 1. Set node offline for > 24h
# 2. Send heartbeat
# 3. Verify status = 'quarantine'
```

### Regression Testing

```bash
# Run full test suite after all changes
cd admin-ui && python -m pytest tests/ -v

# Integration tests for node sync
python -m pytest tests/test_node_sync.py -v

# Scheduler tests
python -m pytest tests/test_scheduler.py -v
```

### Evidence Collection

For each fix, collect:

1. **Before state** - Screenshot or command output showing problem
2. **Fix commit** - Git SHA of change
3. **After state** - Screenshot or command output showing fix
4. **Test results** - pytest output showing passing tests

Store in `.sisyphus/evidence/remediation-rank-N.md`

---

## Quick Reference

### Critical Commands

```bash
# Pre-upgrade baseline
./scripts/pb doctor && ./scripts/pb backup

# Check node states
docker exec admin-ui psql -U powerblockade -c "
  SELECT name, status, version, last_seen FROM nodes;"

# Check retention settings
docker exec admin-ui psql -U powerblockade -c "
  SELECT key, value FROM settings WHERE key LIKE 'retention_%';"

# Run health check
curl -sf http://localhost:8080/health

# Test DNS
dig @127.0.0.1 google.com +short
```

### Rollback Command

```bash
./scripts/pb rollback
```

### Contact Points

- Gap analysis questions: See `docs/GAP_ANALYSIS_RETENTION_NODE_RESILIENCE.md`
- Upgrade procedures: See `docs/UPGRADE_ROLLBACK_VALIDATION_PLAYbook.md`
- Node lifecycle: See `docs/NODE_LIFECYCLE_AND_QUARANTINE_POLICY.md`

---

*Document generated: 2026-03-03*
*Package: Retention Durability and Node Resilience Analysis*
