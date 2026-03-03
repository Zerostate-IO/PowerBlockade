# Node Lifecycle and Quarantine Policy

**Document Version**: 2.0  
**Date**: 2026-03-03  
**Status**: Policy Specification

---

## 1. Policy Scope

This document defines:

- **Node lifecycle states** and their semantics
- **Transition triggers** between states with timeout values
- **Quarantine policy** for nodes returning after extended absence
- **Version compatibility gates** for primary/secondary synchronization
- **Incident response procedures** for days-absent nodes

### 1.1 Scope Boundaries

| In Scope | Out of Scope |
|----------|--------------|
| Node state transitions | DNS resolution logic |
| Quarantine entry/exit | RPZ zone content |
| Version compatibility checks | Metrics collection implementation |
| Heartbeat monitoring | Network partition recovery (handled by sync-agent buffering) |

### 1.2 Applicable Components

| Component | Role |
|-----------|------|
| **admin-ui** | State machine owner, transition enforcement, quarantine/release |
| **sync-agent** | Heartbeat sender, version reporter (no state authority) |
| **dnstap-processor** | Ingest pipeline (respects quarantine blocks) |

**Key Principle**: The sync-agent never owns state transitions. It reports health; admin-ui decides state.

---

## 2. State Definitions

### 2.1 State Machine Overview

```
┌─────────┐    register     ┌────────┐
│ PENDING │ ──────────────► │ ACTIVE │◄──────────────────┐
└─────────┘                 └────────┘                   │
                               │  │                      │
                     heartbeat │  │ stale_timeout        │
                     (healthy) │  │ (warning)            │
                               ▼  ▼                      │
                           ┌────────┐                    │
                           │ STALE  │───────┐            │
                           └────────┘       │            │
                               │            │ heartbeat  │
                               │ offline_   │ (recovery) │
                               │ timeout    │            │
                               ▼            │            │
                           ┌──────────┐     │            │
                           │ OFFLINE  │─────┤            │
                           └──────────┘     │            │
                               │            │            │
                     return_   │            │            │
                     after_    │            │            │
                     long_     │            │            │
                     absence   │            │            │
                               ▼            │            │
                           ┌────────────┐   │            │
                           │ QUARANTINE │───┼────────────┘
                           └────────────┘   │ manual_release
                               │            │
                      sync_    │            │
                      failure  │            │
                               ▼            │
                           ┌────────┐       │
                           │ ERROR  │◄──────┘
                           └────────┘  manual_set
```

### 2.2 State Reference Table

| State | Description | Entry Criteria | Exit Criteria | UI Indicator |
|-------|-------------|----------------|---------------|--------------|
| **PENDING** | Node registered with API key but not yet synced | Initial node creation with API key | First successful `register` call | ⏳ Yellow |
| **ACTIVE** | Node is healthy and syncing normally | Successful `register` or `heartbeat` (when not in ERROR/QUARANTINE) | Timeout expiry to STALE/OFFLINE | ✅ Green |
| **STALE** | Heartbeat overdue (warning state) | `last_seen` > `stale_minutes` but < `offline_minutes` | Heartbeat resumes → ACTIVE; Extended absence → OFFLINE | ⚠️ Orange |
| **OFFLINE** | Heartbeat significantly overdue | `last_seen` > `offline_minutes` | Return after absence → QUARANTINE (if > threshold) or ACTIVE | 🔴 Red |
| **QUARANTINE** | Returned after long absence, pending verification | Node returns after `last_seen` > `quarantine_threshold` | Manual approval after compatibility/drift check | 🔒 Gray |
| **ERROR** | Sync failure requiring intervention | Operator manually sets or automated failure detection | Manual intervention and status clear | ❌ Red |

---

## 3. Transition Rules

### 3.1 Transition Matrix

| From | To | Trigger | Owner | Timeout |
|------|-----|---------|-------|---------|
| PENDING | ACTIVE | Successful `register` call | admin-ui | Immediate |
| ACTIVE | STALE | `last_seen` age > `stale_minutes` | admin-ui (periodic check) | 5 minutes (default) |
| STALE | ACTIVE | Successful `heartbeat` | admin-ui | Immediate |
| STALE | OFFLINE | `last_seen` age > `offline_minutes` | admin-ui (periodic check) | 30 minutes (default) |
| OFFLINE | QUARANTINE | Node returns after `last_seen` > `quarantine_threshold` | admin-ui | On first heartbeat |
| OFFLINE | ACTIVE | Node returns within `quarantine_threshold` | admin-ui | On first heartbeat |
| QUARANTINE | ACTIVE | Manual approval after verification | Operator (via admin-ui) | Manual |
| QUARANTINE | ERROR | Compatibility/drift check fails | admin-ui | Automatic |
| ERROR | ACTIVE | Manual intervention complete | Operator (via admin-ui) | Manual |
| Any | ERROR | Operator manual set | Operator | Manual |

### 3.2 Transition Logging

All state transitions must be logged with:

```json
{
  "timestamp": "2026-03-03T12:00:00Z",
  "node_id": "node-uuid",
  "from_state": "OFFLINE",
  "to_state": "QUARANTINE",
  "trigger": "return_after_threshold",
  "metadata": {
    "offline_duration_minutes": 1440,
    "last_seen": "2026-03-02T12:00:00Z"
  }
}
```

---

## 4. Quarantine Policy

### 4.1 Entry Criteria

A node enters QUARANTINE when:

1. **Was OFFLINE** (`last_seen` > `offline_minutes`)
2. **Returns** (sends heartbeat/register)
3. **Absence exceeded threshold** (`offline_duration > quarantine_threshold_minutes`)

**Pseudocode**:

```python
if node.status == "offline" and heartbeat_received:
    offline_duration = now - node.last_seen
    if offline_duration > quarantine_threshold:
        node.status = "quarantine"
        node.quarantine_entry_time = now
        node.quarantine_reason = f"Returned after {offline_duration} offline"
    else:
        node.status = "active"
```

### 4.2 Quarantine Restrictions

While in quarantine, a node:

| Action | Allowed | Rationale |
|--------|---------|-----------|
| Send heartbeats | ✅ Yes | Monitoring maintained |
| Pull configuration | ❌ No | Prevent stale config application |
| Push metrics | ❌ No | Prevent data corruption |
| Ingest events | ❌ No | Prevent duplicate/anomalous data |
| Be queried for diagnostics | ✅ Yes | Troubleshooting support |

### 4.3 Exit Checks

Before releasing from QUARANTINE, the following checks must pass:

| Check | Pass Condition | Failure Action |
|-------|----------------|----------------|
| **Version compatibility** | Node version within supported skew of primary | Block release, show warning |
| **Config drift** | Node's `config_version` matches primary | Force full sync before release |
| **Metrics sanity** | Recent metrics not anomalous | Flag for investigation |
| **Manual approval** | Operator explicitly approves | Required for release |

### 4.4 Release Workflow

**Manual Release (Recommended Default)**:

1. Admin reviews node in UI
2. System displays:
   - Offline duration
   - Version comparison
   - Config drift status
   - Last known metrics
3. Admin clicks "Approve" or "Reject"
4. If approved:
   - Status → ACTIVE
   - `approved_by` and `approved_at` recorded
   - Full config sync triggered
5. If rejected:
   - Status → ERROR
   - Reason recorded in `quarantine_reason`

**Automatic Release (Opt-in)**:

| Setting | Default | Description |
|---------|---------|-------------|
| `quarantine_auto_release` | `false` | Enable automatic release when all checks pass |

**Risk Acceptance**: Automatic release is an opt-in risk acceptance and should only be enabled in controlled environments.

---

## 5. Compatibility Gates

### 5.1 Version Comparison Logic

```python
def check_version_compatibility(primary: str, secondary: str) -> tuple[str, str]:
    """
    Returns (status, message) where status is ALLOW, WARN, or BLOCK.
    """
    # Handle unknown versions
    if primary == "unknown" and secondary == "unknown":
        return ("ALLOW", "Both versions unknown, assuming compatibility")
    if primary == "unknown":
        return ("WARN", f"Primary version unknown, cannot verify secondary {secondary}")
    if secondary == "unknown":
        return ("WARN", f"Secondary version unknown, cannot verify against primary {primary}")

    # Parse versions
    try:
        p_major, p_minor, p_patch = map(int, primary.split("."))
        s_major, s_minor, s_patch = map(int, secondary.split("."))
    except ValueError:
        return ("WARN", f"Unparseable version: primary={primary}, secondary={secondary}")

    # Major version mismatch = BLOCK
    if p_major != s_major:
        return ("BLOCK", f"Major version mismatch: primary={primary}, secondary={secondary}")

    # Minor version mismatch = WARN
    if p_minor != s_minor:
        return ("WARN", f"Minor version skew: primary={primary}, secondary={secondary}")

    # Patch version behind = WARN, ahead or equal = ALLOW
    if s_patch < p_patch:
        return ("WARN", f"Secondary patch behind: primary={primary}, secondary={secondary}")

    return ("ALLOW", f"Versions compatible: primary={primary}, secondary={secondary}")
```

### 5.2 Compatibility Matrix

| Primary Version | Secondary Version | Status | Operator Action |
|-----------------|-------------------|--------|-----------------|
| `X.Y.Z` | `X.Y.Z` (identical) | **ALLOW** | None required |
| `X.Y.Z` | `X.Y.Z+1` (patch ahead) | **ALLOW** | Monitor logs |
| `X.Y.Z` | `X.Y.Z-1` (patch behind) | **WARN** | Schedule secondary update |
| `X.Y.Z` | `X.Y+1.0` (minor ahead) | **WARN** | Consider primary upgrade |
| `X.Y.Z` | `X.Y-1.0` (minor behind) | **WARN** | Update secondary |
| `X.Y.Z` | `X+1.0.0` (major ahead) | **BLOCK** | Downgrade secondary or upgrade primary |
| `X.Y.Z` | `X-1.0.0` (major behind) | **BLOCK** | Update secondary to current major |
| `X.Y.Z` | `unknown` | **WARN** | Check `PB_VERSION` on secondary |
| `unknown` | `X.Y.Z` | **WARN** | Check `PB_VERSION` on primary |

### 5.3 Status Actions

| Status | Config Sync | Log Level | UI Badge |
|--------|-------------|-----------|----------|
| **ALLOW** | Proceeds normally | DEBUG | Green checkmark |
| **WARN** | Proceeds with warning | WARNING | Amber warning |
| **BLOCK** | Halted (HTTP 409) | ERROR | Red error, node → ERROR |

### 5.4 Recommended Skew Policy

| Skew Type | Max Allowed | Rationale |
|-----------|-------------|-----------|
| Patch | Unlimited | Patches are backward compatible |
| Minor | ±1 version | Feature additions should be gradual |
| Major | 0 (must match) | Breaking changes require coordinated upgrade |

---

## 6. Configuration

### 6.1 Default Thresholds

| Setting | Default | Configurable | Location |
|---------|---------|--------------|----------|
| `stale_minutes` | 5 | Yes | `settings.health_stale_minutes` |
| `offline_minutes` | 30 | Yes | `settings.health_offline_minutes` |
| `quarantine_threshold_minutes` | 1440 (24h) | Yes | `settings.health_quarantine_threshold_minutes` |
| `heartbeat_interval_seconds` | 60 | Yes | sync-agent env `HEARTBEAT_INTERVAL_SECONDS` |
| `config_sync_interval_seconds` | 300 | Yes | sync-agent env `CONFIG_SYNC_INTERVAL_SECONDS` |
| `metrics_buffer_max_age_seconds` | 604800 (7d) | Yes | sync-agent env `METRICS_BUFFER_MAX_AGE` |

### 6.2 Current Implementation Status

| Setting | Current State | Required State |
|---------|---------------|----------------|
| Stale threshold | `health_stale_minutes` (5) ✅ | Same |
| Offline threshold | **Not implemented** | `health_offline_minutes` (30) |
| Quarantine threshold | **Not implemented** | `health_quarantine_threshold_minutes` (1440) |

### 6.3 Override Mechanism

Thresholds can be overridden at multiple levels:

| Level | Mechanism | Scope |
|-------|-----------|-------|
| **Global** | Settings table | All nodes |
| **Per-node** | Node-specific override column | Individual node |
| **Environment** | Container environment variables | Sync-agent behavior |

**Settings Table Override**:

```sql
-- Override global stale threshold
UPDATE settings SET value = '10' WHERE key = 'health_stale_minutes';

-- Per-node override (requires schema extension)
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS stale_override_minutes INTEGER;
```

**Environment Override (sync-agent)**:

```bash
# In .env or docker-compose
HEARTBEAT_INTERVAL_SECONDS=120
CONFIG_SYNC_INTERVAL_SECONDS=600
METRICS_BUFFER_MAX_AGE=86400  # 1 day for testing
```

---

## 7. Incident Response

### 7.1 Long-Absent Node Procedure

When a node returns after being offline for days:

**Step 1: Detection**

```bash
# Check for nodes offline > 24 hours
docker exec admin-ui psql -U postgres -d powerblockade -c \
  "SELECT name, status, last_seen,
    EXTRACT(EPOCH FROM (NOW() - last_seen))/3600 as hours_offline
   FROM nodes 
   WHERE last_seen < NOW() - INTERVAL '24 hours'
   ORDER BY last_seen DESC;"
```

**Step 2: Automatic Quarantine**

If node returns after > `quarantine_threshold_minutes` (default 24h):

1. Node automatically enters QUARANTINE state
2. `quarantine_entry_time` and `quarantine_reason` recorded
3. Alert fired to monitoring

**Step 3: Assessment Checklist**

| Check | Command | Pass Criteria |
|-------|---------|---------------|
| Version match | `SELECT version FROM nodes WHERE name = 'X'` | Same major, ±1 minor |
| Config drift | Compare `config_version` with primary | Must match |
| Metrics sanity | Review last pushed metrics | No anomalies |
| DNS resolution | `dig @node-ip test.domain` | Returns expected result |

**Step 4: Release Decision**

| Scenario | Action |
|----------|--------|
| All checks pass, node trusted | Approve → ACTIVE |
| Version mismatch | Update node, retry |
| Config drift detected | Force full sync, verify, then approve |
| Suspicious activity | Reject → ERROR, investigate |

**Step 5: Post-Release Verification**

```bash
# Verify node is syncing
docker exec admin-ui psql -U postgres -d powerblockade -c \
  "SELECT name, status, last_seen, version, config_version
   FROM nodes WHERE name = 'X';"

# Check recent heartbeats
docker logs sync-agent --since 5m | grep -i heartbeat
```

### 7.2 Days-Absent Node Flowchart

```
Node Returns After Days Offline
              │
              ▼
    ┌─────────────────────┐
    │ Offline > 24 hours? │
    └──────────┬──────────┘
               │
        ┌──────┴──────┐
        │             │
       Yes           No
        │             │
        ▼             ▼
  ┌──────────┐   ┌──────────┐
  │QUARANTINE│   │  ACTIVE  │
  └────┬─────┘   └──────────┘
       │
       ▼
┌─────────────────────┐
│ Version Compatible? │
└──────────┬──────────┘
           │
    ┌──────┴──────┐
    │             │
   Yes           No
    │             │
    ▼             ▼
┌────────┐   ┌────────────────┐
│ Config │   │ ERROR          │
│ Sync   │   │ "Version mismatch"
└────┬───┘   └────────────────┘
     │
     ▼
┌──────────────────┐
│ Config Version   │
│ Matches Primary? │
└────────┬─────────┘
         │
  ┌──────┴──────┐
  │             │
 Yes           No
  │             │
  ▼             ▼
┌────────┐  ┌─────────────┐
│ Manual │  │ Force Sync  │
│Approve │  │ Then Approve│
└────┬───┘  └─────────────┘
     │
     ▼
┌──────────┐
│  ACTIVE  │
└──────────┘
```

### 7.3 Rollback Procedure

If a released node causes issues:

```bash
# 1. Immediately quarantine
curl -X POST http://localhost:8080/api/nodes/{node_id}/quarantine \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"reason": "Post-release issues detected"}'

# 2. Review state history
docker exec admin-ui psql -U postgres -d powerblockade -c \
  "SELECT * FROM node_state_history 
   WHERE node_id = (SELECT id FROM nodes WHERE name = 'X')
   ORDER BY created_at DESC LIMIT 10;"

# 3. Investigate logs
docker logs sync-agent --since 1h | grep -i error
```

---

## 8. Verification Commands

### 8.1 Check Node States

```bash
# List all nodes with status and last_seen
docker exec admin-ui psql -U postgres -d powerblockade -c \
  "SELECT name, status, last_seen, 
    EXTRACT(EPOCH FROM (NOW() - last_seen))/60 as minutes_since_seen
   FROM nodes ORDER BY last_seen DESC;"
```

### 8.2 Check Stale Nodes

```bash
# Nodes where last_seen > stale_minutes (5 min default)
docker exec admin-ui psql -U postgres -d powerblockade -c \
  "SELECT name, status, last_seen,
    EXTRACT(EPOCH FROM (NOW() - last_seen))/60 as minutes_stale
   FROM nodes 
   WHERE last_seen < NOW() - INTERVAL '5 minutes'
   ORDER BY last_seen DESC;"
```

### 8.3 Check Quarantine Status

```bash
# Nodes in quarantine
docker exec admin-ui psql -U postgres -d powerblockade -c \
  "SELECT name, status, quarantine_entry_time, quarantine_reason,
    approved_by, approved_at
   FROM nodes WHERE status = 'quarantine';"
```

### 8.4 Check Version Compatibility

```bash
# Compare all node versions with primary
docker exec admin-ui psql -U postgres -d powerblockade -c \
  "SELECT n.name, n.version as node_version, 
    (SELECT value FROM settings WHERE key = 'pb_version') as primary_version
   FROM nodes n;"
```

---

## 9. Implementation Status

### 9.1 Completed

- [x] `NodeStatus` enum defines all states
- [x] Heartbeat endpoint receives and updates `last_seen`
- [x] Sync-agent sends heartbeats with version
- [x] Stale detection generates UI warnings

### 9.2 In Progress

- [ ] Automatic STALE → OFFLINE state transitions
- [ ] Quarantine-on-return for long-absent nodes
- [ ] Configurable offline/quarantine thresholds

### 9.3 Planned

- [ ] Quarantine release workflow UI
- [ ] Version compatibility enforcement
- [ ] State transition history table
- [ ] Per-node threshold overrides

---

## 10. Acceptance Criteria

- [x] Default thresholds documented (5min stale, 30min offline, 24h quarantine)
- [x] Override mechanism defined (settings table + environment variables)
- [x] Quarantine-on-return explicit (entry criteria, exit checks, workflow)
- [x] Incident response path for days-absent nodes (detection, assessment, release, rollback)
