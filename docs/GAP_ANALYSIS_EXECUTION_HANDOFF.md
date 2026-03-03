# Gap Analysis: Execution Handoff

**Generated**: 2026-03-03
**Purpose**: Concise execution packet linking report, policies, backlog, and next actions

---

## 1. Scope

This plan addresses four critical domains identified in the gap analysis:

| Domain | Coverage |
|--------|----------|
| **UI Data Truthfulness** | Dashboard accuracy, empty states, error handling |
| **Retention Durability** | Data persistence, buffer survival through upgrades |
| **Upgrade/Rollback Coherence** | Pre/post verification, drift detection, rollback safety |
| **Node Lifecycle/Recovery** | State machine, quarantine policy, version gates |

**Total Findings**: 17 gaps (2 P0, 6 P1, 6 P2, 3 P3)

---

## 2. Top 5 Risks

| Rank | Risk | Impact | Fix Location |
|------|------|--------|--------------|
| **1** | Advisory lock fallback runs job on error | Duplicate blocklists, double rollups, race conditions | `scheduler.py:67` |
| **2** | sync-agent metrics buffer not persisted | Up to 7 days metrics lost on container recreation | `compose.yaml` volumes |
| **3** | Node state transitions not automated | Stale nodes appear "active", no health visibility | `scheduler.py` new job |
| **4** | Version compatibility not enforced | Major version mismatch allows breaking config sync | `node_sync.py` |
| **5** | Quarantine-on-return not implemented | Long-offline nodes resume without verification | `node_sync.py:84-108` |

---

## 3. Critical Path

```
Phase 1 (Week 1): Data Safety
├── Rank 1: Fix lock fallback ─────────────────────┐
└── Rank 2: Add sync-agent volume                  │
                                                   ▼
Phase 2 (Week 2): Operational Safety        Rank 6: Add locks to
├── Rank 3: State transitions ◄───────────── remaining jobs
├── Rank 4: Version enforcement ◄──────────────────┤
├── Rank 5: Quarantine entry ◄─────────────────────┤
└── Rank 7: Configurable thresholds                │
                                                   │
Phase 3 (Week 3+): Resilience                      │
├── Rank 8: Event buffering                        │
├── Rank 9: Metrics unique constraint              │
├── Rank 10: Audit retention                       │
└── Ranks 11-17: UX polish                         │
```

**Shortest path to production safety**: Ranks 1, 2, 3 (3 items)
**Full node lifecycle safety**: Ranks 1-5, 7 (6 items)

---

## 4. Immediate Actions

### Week 1 - Data Safety (P0 Items)

**Action 1.1: Fix Advisory Lock Fallback**
```python
# admin-ui/app/services/scheduler.py
# Change line ~67 from:
except Exception:
    return func(*args, **kwargs)  # WRONG: runs job anyway

# To:
except Exception:
    logger.warning(f"Could not acquire lock for {func.__name__}, skipping")
    return None  # CORRECT: skip job safely
```

**Action 1.2: Add sync-agent Volume**
```yaml
# compose.yaml - add to sync-agent service:
services:
  sync-agent:
    volumes:
      - sync-agent-buffer:/var/lib/powerblockade

# Add to volumes section:
volumes:
  sync-agent-buffer:
```

### Week 2 - Operational Safety (P1 Items)

**Action 2.1: Add State Transition Job**
```python
# admin-ui/app/services/scheduler.py - new job:
@run_with_advisory_lock("node_state_transitions")
def transition_node_states():
    stale_threshold = get_setting("health_stale_minutes", 5)
    offline_threshold = get_setting("health_offline_minutes", 30)
    
    # ACTIVE -> STALE
    db.execute("""
        UPDATE nodes SET status = 'stale'
        WHERE status = 'active'
        AND last_seen < NOW() - INTERVAL '%s minutes'
    """, stale_threshold)
    
    # STALE -> OFFLINE
    db.execute("""
        UPDATE nodes SET status = 'offline'
        WHERE status = 'stale'
        AND last_seen < NOW() - INTERVAL '%s minutes'
    """, offline_threshold)
```

**Action 2.2: Add Version Enforcement**
```python
# admin-ui/app/routers/node_sync.py - add to heartbeat handler:
def check_version_compatibility(primary: str, secondary: str) -> tuple[str, str]:
    p_major, _, _ = map(int, primary.split("."))
    s_major, _, _ = map(int, secondary.split("."))
    if p_major != s_major:
        return ("BLOCK", f"Major version mismatch: primary={primary}, secondary={secondary}")
    return ("ALLOW", "Versions compatible")

# Block sync on BLOCK status
status, msg = check_version_compatibility(primary_version, node.version)
if status == "BLOCK":
    raise HTTPException(409, msg)
```

**Action 2.3: Add Quarantine-on-Return**
```python
# admin-ui/app/routers/node_sync.py - modify heartbeat handler:
if node.status == "offline":
    offline_duration = datetime.utcnow() - node.last_seen
    quarantine_threshold = get_setting("health_quarantine_threshold_minutes", 1440)
    
    if offline_duration.total_seconds() > quarantine_threshold * 60:
        node.status = "quarantine"
        node.quarantine_entry_time = datetime.utcnow()
        node.quarantine_reason = f"Returned after {offline_duration}"
    else:
        node.status = "active"
```

---

## 5. Dependencies

| Item | Depends On | Blocks |
|------|------------|--------|
| Rank 6 (Locks on jobs) | Rank 1 (Fix fallback first) | Nothing |
| Rank 4 (Version enforcement) | Rank 3 (State transitions) | Rank 5, Rank 15 |
| Rank 5 (Quarantine entry) | Rank 3, Rank 4 | Rank 16 (Exit checks) |
| Rank 7 (Thresholds) | Rank 3, Rank 5 | Nothing |
| Rank 16 (Quarantine exit) | Rank 4, Rank 5 | Nothing |
| Rank 9 (Unique constraint) | Rank 6 (Lock on local_metrics) | Nothing |

---

## 6. Assumptions and Defaults

### Explicit Defaults (Need Documentation)

| Setting | Default | Must Be Configured |
|---------|---------|-------------------|
| `health_stale_minutes` | 5 | No (sensible default) |
| `health_offline_minutes` | 30 | **Yes** - add to settings model |
| `health_quarantine_threshold_minutes` | 1440 (24h) | **Yes** - add to settings model |
| `quarantine_auto_release` | false | **Yes** - risk acceptance |

### Assumptions

| Assumption | Risk if Wrong |
|------------|---------------|
| Single admin-ui instance | Duplicate job execution if scaled |
| Prometheus on default retention | Metrics gaps if retention < DB retention |
| Docker named volumes survive `down` | Data loss if `down -v` used |
| sync-agent heartbeat interval = 60s | Stale detection timing mismatch |

### Values That Must Be Explicitly Documented

1. **Node health thresholds** - currently hardcoded or missing in settings
2. **Single-instance constraint** - not documented in compose.yaml
3. **Prometheus vs DB retention alignment** - not documented in setup
4. **Buffer max age values** - only in environment variables

---

## 7. Next Steps

### Ordered Execution Sequence

```
1. [P0] Fix advisory lock fallback (scheduler.py)
2. [P0] Add sync-agent volume (compose.yaml)
3. [P1] Add health_offline_minutes to settings model
4. [P1] Add health_quarantine_threshold_minutes to settings model
5. [P1] Implement state transition periodic job
6. [P1] Implement check_version_compatibility() with BLOCK logic
7. [P1] Add quarantine-on-return to heartbeat handler
8. [P1] Add advisory locks to precache_warming, local_metrics, blocklist_schedule
9. [P2] Add UniqueConstraint to node_metrics
10. [P2] Add retention for config_changes
11. [P2-P3] UX improvements (empty states, settings feedback, version badges)
```

### Verification After Each Step

```bash
# After steps 1-2:
./scripts/pb doctor

# After steps 3-8:
cd admin-ui && python -m pytest tests/ -v

# After steps 9-10:
docker compose exec postgres psql -U powerblockade -c "SELECT count(*) FROM node_metrics;"

# Full verification:
grep -A5 "except Exception" admin-ui/app/services/scheduler.py | head -10
grep -A20 "sync-agent:" compose.yaml | grep -A5 "volumes:"
```

---

## Reference Documents

| Document | Purpose |
|----------|---------|
| `docs/GAP_ANALYSIS_RETENTION_NODE_RESILIENCE.md` | Full gap report with evidence |
| `docs/NODE_LIFECYCLE_AND_QUARANTINE_POLICY.md` | State machine and quarantine policy |
| `docs/UPGRADE_ROLLBACK_VALIDATION_PLAYBOOK.md` | Pre/post upgrade verification |
| `.sisyphus/evidence/task-8-remediation-backlog.md` | Full 17-item prioritized backlog |

---

*Document generated: 2026-03-03*
