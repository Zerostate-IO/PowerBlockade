# Gap Analysis: Retention Durability and Node Resilience

**Generated**: 2026-03-03  
**Scope**: PowerBlockade data integrity, upgrade safety, and multi-node reliability

---

## Executive Summary

This analysis identifies 17 gaps across four critical domains: UI data truthfulness, retention durability, upgrade/rollback coherence, and node lifecycle management. The top 5 risks require immediate attention to prevent data loss, silent corruption, or operational failures.

### Top 5 Risks and Immediate Actions

| Priority | Risk | Impact | Immediate Action |
|----------|------|--------|------------------|
| **P0-1** | Advisory lock fallback runs job on error | Duplicate blocklist updates, double rollups, race conditions | Change `scheduler.py:67` to skip job instead of running |
| **P0-2** | sync-agent metrics buffer not persisted | Up to 7 days of secondary node metrics lost on upgrade | Add volume `sync-agent-buffer:/var/lib/powerblockade` to compose.yaml |
| **P1-3** | Node state transitions not implemented | Stale nodes appear "active"; no accurate health visibility | Add periodic job to transition ACTIVE\u2192STALE\u2192OFFLINE |
| **P1-4** | Version compatibility checks not enforced | Major version mismatch allows breaking config sync | Implement `check_version_compatibility()` with BLOCK logic |
| **P1-5** | Quarantine-on-return not implemented | Long-offline nodes resume without verification | Check offline duration in heartbeat, set QUARANTINE if > 24h |

### Recommended Remediation Path

```
Week 1: Ranks 1, 2 (P0 items - data loss prevention)
Week 2: Ranks 3, 4, 5 (P1 items - operational safety)
Week 3+: Ranks 6-17 (P2/P3 items - polish and resilience)
```

---

## 1. UI Data Truthfulness

### Summary

The admin-ui dashboard, logs, and settings pages generally display accurate data from PostgreSQL. However, several empty-state and error-handling inconsistencies create user confusion.

### Findings

#### 1.1 Dashboard Statistics Accurate

The main dashboard (`index.html`) correctly aggregates data from:
- `dns_query_events` \u2192 query counts, blocked counts, hit rate
- `node_metrics` \u2192 per-node telemetry
- `settings` \u2192 health thresholds for warnings

**Evidence**: `admin-ui/app/routers/analytics.py:60-134` - Numeric fallbacks use `or 0`, preventing NaN displays.

#### 1.2 Live Query Stream Requires Auth

WebSocket stream at `/ws/stream` correctly validates `user_id` against the `users` table. Invalid users receive close codes 4001/4003.

**Evidence**: `admin-ui/app/routers/streaming.py:83-138`

#### 1.3 Empty-State Inconsistencies

| Page | Current Behavior | Expected |
|------|------------------|----------|
| Logs (`logs.html`) | Shows "No queries found." | \u2705 Correct |
| Domains (`domains.html`) | Empty table, no message | \u274c Missing empty state |
| Domains pagination | Shows "Next" on empty | \u274c Should hide |
| Settings (`settings.html`) | No save confirmation | \u274c Missing feedback |

**Evidence**: 
- `admin-ui/app/templates/logs.html:216` - Has empty state
- `admin-ui/app/templates/domains.html:16-31` - No empty state row
- `admin-ui/app/templates/settings.html:10` - No success/error flash

#### 1.4 Redirect Pages Work Correctly

`/blocked` and `/failures` redirect to `/logs?view=blocked|failures`, inheriting correct empty-state handling.

**Evidence**: `admin-ui/app/routers/analytics.py:447-468`

### Remediation Items

- **Rank 11**: Add empty-state message to domains page
- **Rank 14**: Add settings save feedback
- **Rank 17**: Hide pagination on empty domains

---

## 2. Retention Durability

### Summary

PowerBlockade implements retention policies for core data tables, but two critical persistence gaps threaten data durability during container recreation or extended outages.

### Findings

#### 2.1 Core Retention Policies (Working)

| Table | Retention Setting | Default | Cleanup Method |
|-------|-------------------|---------|----------------|
| `dns_query_events` | `retention_events_days` | 15 days | Daily DELETE at 03:00 |
| `query_rollups` | `retention_rollups_days` | 365 days | Daily DELETE at 03:00 |
| `node_metrics` | `retention_node_metrics_days` | 365 days | Daily DELETE at 03:00 |

**Evidence**: 
- `admin-ui/app/models/settings.py:22-44` - Default values
- `admin-ui/app/services/retention.py:67-76` - `run_retention_job()`
- `admin-ui/app/services/scheduler.py` - CronTrigger at hour=3, minute=0

#### 2.2 dnstap-processor Buffer (Working)

BoltDB buffer at `/var/lib/dnstap-processor/buffer.db` persists events during primary outages.

| Config | Value |
|--------|-------|
| Volume | `dnstap-buffer` (named volume) |
| Max size | 100MB (`BUFFER_MAX_BYTES`) |
| Max age | 24h (`BUFFER_MAX_AGE`) |

**Evidence**: `dnstap-processor/internal/buffer/buffer.go` - `Put()`, `Peek()`, `Delete()`, `Prune()`

#### 2.3 sync-agent Metrics Buffer (BROKEN)

**Critical Gap**: sync-agent writes metrics to `/var/lib/powerblockade/metrics.db` but no Docker volume maps this path.

| Impact | Severity |
|--------|----------|
| Container recreation loses up to 7 days of buffered metrics | P0-Critical |
| Only affects secondary nodes during primary outage | Medium blast radius |

**Evidence**: 
- `sync-agent/agent.py:287-288` - Buffer path config
- `compose.yaml` - No volume for sync-agent buffer path

**Fix**:
```yaml
# Add to compose.yaml sync-agent service:
volumes:
  - sync-agent-buffer:/var/lib/powerblockade

# Add to volumes section:
volumes:
  sync-agent-buffer:
```

#### 2.4 Audit Log Has No Retention

`config_changes` table grows indefinitely. Long-term deployments may accumulate large audit history.

**Evidence**: `admin-ui/app/services/retention.py` - No cleanup for config_changes

### Remediation Items

- **Rank 2**: Add volume for sync-agent metrics buffer (P0)
- **Rank 10**: Add retention for config_changes audit log (P2)

---

## 3. Upgrade/Rollback Coherence

### Summary

The `pb update` and `pb rollback` scripts implement database backup and restore workflows. Pre/post upgrade verification commands exist but are not automated into the upgrade flow.

### Findings

#### 3.1 Upgrade Workflow

```
pb update
\u251c\u2500\u2500 backup_database()     \u2192 shared/backups/pre-upgrade-TIMESTAMP.sql
\u251c\u2500\u2500 backup_config()       \u2192 shared/backups/config-TIMESTAMP.tar.gz
\u251c\u2500\u2500 Pull images           \u2192 docker compose pull
\u251c\u2500\u2500 run_migrations()      \u2192 alembic upgrade head
\u251c\u2500\u2500 Restart services      \u2192 docker compose up -d
\u251c\u2500\u2500 verify_health()       \u2192 /health + DNS test
\u2514\u2500\u2500 save_state()          \u2192 .pb-state.json
```

**Evidence**: `scripts/pb:437-528` - `cmd_update()` function

#### 3.2 Rollback Workflow

```
pb rollback
\u251c\u2500\u2500 Read .pb-state.json   \u2192 previous_version, last_db_backup
\u251c\u2500\u2500 Stop services         \u2192 docker compose down
\u251c\u2500\u2500 Restore DB (optional) \u2192 psql < backup.sql
\u251c\u2500\u2500 Start services        \u2192 docker compose up -d
\u2514\u2500\u2500 verify_health()
```

**Evidence**: `scripts/pb:530-602` - `cmd_rollback()` function

#### 3.3 Volume Preservation

Named volumes survive `docker compose down`:
- `postgres-data` - Primary database
- `prometheus-data` - Metrics TSDB
- `grafana-data` - Dashboards
- `dnstap-buffer` - Event buffer

**Evidence**: `compose.yaml:299-307` - Named volumes list

#### 3.4 Pre/Post-Upgrade Verification (Manual)

The evidence document provides comprehensive checklists but they are not integrated into `pb update`:

**Pre-upgrade**:
- Service health baseline (`pb doctor`)
- Database integrity check
- Row count capture
- Retention settings snapshot
- Prometheus metrics baseline

**Post-upgrade**:
- Migration verification (`alembic current`)
- Data continuity (row count diff)
- Observability alignment (Prometheus targets)
- Ingestion test (dig + DB check)

**Evidence**: `.sisyphus/evidence/task-3-upgrade-retention-checks.md:49-341`

#### 3.5 Rollback Drift Detection

Rollback verification includes:
- Schema drift check (`alembic check`)
- Orphaned data detection
- Retention setting validation
- Data continuity (rollup gaps)

**Evidence**: `.sisyphus/evidence/task-3-upgrade-retention-checks.md:425-460`

### Recommendations

1. Integrate pre-upgrade checks into `pb update --preflight`
2. Add post-upgrade verification to `pb update` (auto-rollback on failure)
3. Document rollback procedure with data-loss scenarios

---

## 4. Node Lifecycle/Recovery

### Summary

The node lifecycle state machine is defined but not fully implemented. Nodes can get stuck in incorrect states, and returning nodes bypass quarantine verification.

### Findings

#### 4.1 State Machine (Defined but Incomplete)

```
PENDING \u2192 ACTIVE \u2192 STALE \u2192 OFFLINE \u2192 QUARANTINE \u2192 ACTIVE
                    \u2191         \u2193            \u2193
                    \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
                     (manual or auto)
```

**Current Implementation**:
- `NodeStatus` enum exists: PENDING, ACTIVE, STALE, OFFLINE, QUARANTINE, ERROR
- Heartbeat sets ACTIVE (unless already ERROR/QUARANTINE)
- **Missing**: Periodic job to transition ACTIVE\u2192STALE\u2192OFFLINE

**Evidence**: `admin-ui/app/models/node.py:15-23` - Status enum

#### 4.2 State Transitions Not Automated

| Transition | Expected | Current |
|------------|----------|---------|
| ACTIVE \u2192 STALE | When `last_seen` > `stale_minutes` | Warning only, no status change |
| STALE \u2192 OFFLINE | When `last_seen` > `offline_minutes` | Not implemented |
| OFFLINE \u2192 QUARANTINE | On return after 24h+ offline | Not implemented |

**Evidence**: 
- `admin-ui/app/routers/system.py:100-116` - Warning only
- `admin-ui/app/routers/node_sync.py:103-105` - Sets ACTIVE, no quarantine check

#### 4.3 Quarantine-on-Return Not Implemented

**Critical Gap**: Nodes returning after extended outage should enter QUARANTINE for verification.

| Scenario | Current | Expected |
|----------|---------|----------|
| Node returns after 2 days | ACTIVE immediately | QUARANTINE pending verification |
| Quarantine exit | Manual only | Version check + config sync + approval |

**Evidence**: `admin-ui/app/routers/node_sync.py:84-108` - No quarantine logic

#### 4.4 Version Compatibility Not Enforced

**Critical Gap**: Major version mismatches should BLOCK config sync.

| Primary | Secondary | Matrix Status | Current Behavior |
|---------|-----------|---------------|------------------|
| 1.2.0 | 1.2.0 | ALLOW | \u2705 Works |
| 1.2.0 | 2.0.0 | BLOCK | \u274c Sync proceeds |
| 1.2.0 | 0.9.0 | BLOCK | \u274c Sync proceeds |

**Evidence**: 
- `admin-ui/app/routers/node_sync.py:83,107-108` - Version stored but not checked
- `.sisyphus/evidence/task-5-compatibility-matrix.md` - Full matrix defined

#### 4.5 Node Failure Modes

| Failure Mode | Detection | Recovery | Residual Risk |
|--------------|-----------|----------|---------------|
| Network partition | Agent logs, stale warnings | Auto-retry, metrics buffer | Query history gaps |
| Prolonged offline | `last_seen` age | Manual validation | No auto-quarantine |
| Config sync failure | Agent logs, unchanged version | Retry on interval | Stale policy |
| Metrics push failure | Buffer accumulation | Replay on recovery | Buffer pruned after 7d |

**Evidence**: `.sisyphus/evidence/task-4-node-failure-matrix.md:3-12`

#### 4.6 Missing Threshold Settings

| Setting | Current | Required |
|---------|---------|----------|
| `health_stale_minutes` | 5 (exists) | - |
| `health_offline_minutes` | Missing | Default: 30 |
| `health_quarantine_threshold_minutes` | Missing | Default: 1440 (24h) |

**Evidence**: `admin-ui/app/models/settings.py:41` - Only stale defined

### Remediation Items

- **Rank 3**: Implement periodic state transition job
- **Rank 4**: Add version compatibility enforcement
- **Rank 5**: Implement quarantine-on-return
- **Rank 7**: Add configurable offline/quarantine thresholds
- **Rank 8**: Add event buffering to sync-agent (query history)
- **Rank 16**: Implement quarantine exit checks

---

## 5. Remediation Priorities

### Full Backlog Reference

See `.sisyphus/evidence/task-8-remediation-backlog.md` for the complete 17-item prioritized backlog with:
- Severity classification (P0/P1/P2/P3)
- Blast radius assessment
- Verification commands
- Dependency mapping

### Critical Path

```
\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
\u2502  Phase 1: Data Safety (Week 1)                              \u2502
\u2502  \u251c\u2500\u2500 Rank 1: Fix advisory lock fallback                     \u2502
\u2502  \u2514\u2500\u2500 Rank 2: Add sync-agent volume                          \u2502
\u251c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
\u2502  Phase 2: Operational Safety (Week 2)                       \u2502
\u2502  \u251c\u2500\u2500 Rank 3: Implement state transitions                    \u2502
\u2502  \u251c\u2500\u2500 Rank 4: Add version enforcement                        \u2502
\u2502  \u251c\u2500\u2500 Rank 5: Implement quarantine-on-return                 \u2502
\u2502  \u251c\u2500\u2500 Rank 6: Add locks to remaining jobs                    \u2502
\u2502  \u2514\u2500\u2500 Rank 7: Add configurable thresholds                    \u2502
\u251c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
\u2502  Phase 3: Resilience (Week 3+)                              \u2502
\u2502  \u251c\u2500\u2500 Rank 8: Event buffering for query history              \u2502
\u2502  \u251c\u2500\u2500 Rank 9: Metrics unique constraint                      \u2502
\u2502  \u251c\u2500\u2500 Rank 10: Audit log retention                           \u2502
\u2502  \u2514\u2500\u2500 Ranks 11-17: UX improvements                           \u2502
\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
```

### Quick Verification

```bash
# Check P0 items
grep -A5 "except Exception" admin-ui/app/services/scheduler.py | head -10
grep -A20 "sync-agent:" compose.yaml | grep -A5 "volumes:"

# Check P1 items  
grep -E "stale_minutes|offline_minutes" admin-ui/app/routers/system.py
grep -E "check_version|BLOCK" admin-ui/app/routers/node_sync.py
grep -B5 -A10 "quarantine" admin-ui/app/routers/node_sync.py | head -20

# Run tests
cd admin-ui && python -m pytest tests/ -v
```

---

## Appendix: Evidence Files

| Task | File | Focus |
|------|------|-------|
| Task 1 | `.sisyphus/evidence/task-1-ui-truth-map.md` | UI data sources and empty states |
| Task 2 | `.sisyphus/evidence/task-2-persistence-inventory.md` | Retention policies and volume gaps |
| Task 3 | `.sisyphus/evidence/task-3-upgrade-retention-checks.md` | Pre/post upgrade verification |
| Task 4 | `.sisyphus/evidence/task-4-node-failure-matrix.md` | Failure modes and recovery |
| Task 5 | `.sisyphus/evidence/task-5-compatibility-matrix.md` | Version compatibility rules |
| Task 6 | `.sisyphus/evidence/task-6-lifecycle-contract.md` | State machine and transitions |
| Task 7 | `.sisyphus/evidence/task-7-scheduler-ownership.md` | Job scheduling and locks |
| Task 8 | `.sisyphus/evidence/task-8-remediation-backlog.md` | Prioritized remediation list |

---

*Document generated: 2026-03-03*
