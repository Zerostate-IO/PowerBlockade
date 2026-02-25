# Node Lifecycle and Quarantine Policy

**Document Version**: 1.0  
**Date**: 2026-02-25  
**Status**: Proposed Policy

---

## 1. Overview

This document defines the node lifecycle states, transition rules, and quarantine procedures for PowerBlockade multi-node deployments.

---

## 2. Node States

### 2.1 State Definitions

| State | Description | UI Indicator |
|-------|-------------|--------------|
| `PENDING` | Node registered but has not completed first sync | ⏳ Yellow |
| `ACTIVE` | Node syncing normally within acceptable thresholds | ✅ Green |
| `STALE` | Node has synced before but exceeds staleness threshold | ⚠️ Orange |
| `OFFLINE` | No heartbeat received for extended period | 🔴 Red |
| `QUARANTINE` | Node returned after long absence, pending validation | 🔒 Gray |
| `ERROR` | Sync failure detected, requires intervention | ❌ Red |

### 2.2 State Diagram

```
                    ┌──────────────┐
                    │   PENDING    │
                    └──────┬───────┘
                           │ First sync success
                           ▼
                    ┌──────────────┐
         ┌─────────│   ACTIVE     │◄────────┐
         │         └──────┬───────┘         │
         │                │                 │
         │ Stale          │ Offline         │ Sync success
         │ threshold      │ threshold       │
         ▼                ▼                 │
  ┌──────────────┐  ┌──────────────┐        │
  │    STALE     │  │   OFFLINE    │        │
  └──────┬───────┘  └──────┬───────┘        │
         │                 │                 │
         │ Returns         │ Returns within  │
         │ after long      │ grace period    │
         │ absence         ├─────────────────┘
         │                 │
         │                 │ Returns after
         │                 │ quarantine threshold
         ▼                 ▼
  ┌──────────────────────────────┐
  │         QUARANTINE           │
  └──────────────┬───────────────┘
                 │
                 │ Admin approval
                 │ + validation passed
                 ▼
         ┌──────────────┐
         │   ACTIVE     │
         └──────────────┘

  Any State ────Sync failure───→ ERROR
  ERROR ────Manual fix + sync───→ ACTIVE
```

---

## 3. Threshold Configuration

### 3.1 Default Thresholds

| Threshold | Default | Configurable | Description |
|-----------|---------|--------------|-------------|
| `STALE_THRESHOLD_HOURS` | 4 | Yes | Time since last sync before marked stale |
| `OFFLINE_THRESHOLD_HOURS` | 24 | Yes | Time without heartbeat before marked offline |
| `QUARANTINE_THRESHOLD_HOURS` | 72 | Yes | Time offline before quarantine required |
| `HEARTBEAT_INTERVAL_SECONDS` | 60 | Yes | Expected heartbeat frequency |

### 3.2 Configuration Storage

Thresholds should be stored in the `settings` table:

```sql
INSERT INTO settings (key, value) VALUES
  ('stale_threshold_hours', '4'),
  ('offline_threshold_hours', '24'),
  ('quarantine_threshold_hours', '72'),
  ('heartbeat_interval_seconds', '60');
```

### 3.3 Admin UI Configuration

Add threshold configuration to Settings page under "Node Management" section.

---

## 4. Heartbeat Mechanism

### 4.0 Current State (Existing Implementation)

**Heartbeat already exists** in the codebase:
- `sync-agent/agent.py`: Sends heartbeat every `HEARTBEAT_INTERVAL_SECONDS` (default: 60s)
- `admin-ui/app/routers/node_sync.py:93-112`: Receives heartbeat and updates `last_seen`

**Current Implementation Gaps**:
1. No background job detects stale/offline nodes from `last_seen` field
2. Heartbeat blindly sets `status = "active"` without state machine validation
3. No version compatibility check on heartbeat

### 4.1 Sync Agent Heartbeat (Current + Enhancements)

**Frequency**: Every `HEARTBEAT_INTERVAL_SECONDS` (default: 60 seconds) - ALREADY IMPLEMENTED

**Payload** (current + proposed additions):
```json
{
  "node_id": "node-uuid",
  "version": "1.2.0",           // ← ALREADY SENT
  "last_sync_position": 12345678, // ← PROPOSED: for gap detection
  "metrics": {
    "queries_processed": 1000,
    "cache_hits": 800,
    "cache_misses": 200
  },
  "timestamp": "2026-02-25T12:00:00Z"
}
```

### 4.2 Master Response

```json
{
  "status": "active",
  "config_version": 42,
  "required_sync_position": 12345000,
  "warnings": []
}
```

### 4.3 Heartbeat Failure Handling

| Consecutive Failures | Action |
|---------------------|--------|
| 1-3 | Log warning, continue |
| 4-10 | Log error, exponential backoff |
| >10 | Mark node as OFFLINE after threshold |

### 4.4 Required Fixes to Existing Heartbeat

1. **State Machine Guard**: Don't set `status = "active"` if current status is ERROR or QUARANTINE
2. **Detection Job**: Add scheduler job to check `last_seen` and transition ACTIVE→STALE→OFFLINE
3. **Version Check**: Validate `version` field against compatibility matrix
---

## 5. Quarantine Flow

### 5.1 Entry to Quarantine

A node enters quarantine when:

1. **Long Offline Return**: Node was OFFLINE for > `QUARANTINE_THRESHOLD_HOURS` and reconnects
2. **Version Incompatibility**: Node version is incompatible with master
3. **Manual Quarantine**: Admin manually quarantines a node

### 5.2 Quarantine Restrictions

While in quarantine, a node:

- ❌ Cannot ingest events
- ❌ Cannot pull configuration
- ❌ Cannot push metrics
- ✅ Can send heartbeats (for monitoring)
- ✅ Can be queried for diagnostics

### 5.3 Validation Requirements

Before exiting quarantine, validate:

| Check | Description | Auto/Manual |
|-------|-------------|-------------|
| Version | Node version is compatible | Automatic |
| Sync Gap | Gap between last sync and current position | Automatic |
| Checksum | Data checksums match (if implemented) | Automatic |
| Admin Approval | Administrator explicitly approves | Manual |

### 5.4 Quarantine Exit

**Automatic Exit** (if all conditions met):
```
1. Version is compatible
2. Sync gap < MAX_SYNC_GAP
3. No checksum errors
4. Auto-approve enabled in settings
```

**Manual Exit**:
```
1. Admin reviews node in UI
2. Admin clicks "Approve" or "Reject"
3. If approved: status → ACTIVE
4. If rejected: status → ERROR, reason recorded
```

---

## 6. State Transition Rules

### 6.1 Transition Matrix

| From | To | Trigger | Automatic? |
|------|-----|---------|------------|
| PENDING | ACTIVE | First successful sync | Yes |
| ACTIVE | STALE | last_sync > STALE_THRESHOLD | Yes |
| ACTIVE | OFFLINE | No heartbeat > OFFLINE_THRESHOLD | Yes |
| STALE | ACTIVE | Successful sync | Yes |
| STALE | OFFLINE | No heartbeat > OFFLINE_THRESHOLD | Yes |
| STALE | QUARANTINE | Returns after > QUARANTINE_THRESHOLD | Yes |
| OFFLINE | ACTIVE | Returns within QUARANTINE_THRESHOLD | Yes |
| OFFLINE | QUARANTINE | Returns after > QUARANTINE_THRESHOLD | Yes |
| QUARANTINE | ACTIVE | Validation passed + approved | Semi-auto |
| QUARANTINE | ERROR | Validation failed | Yes |
| Any | ERROR | Unrecoverable sync error | Yes |
| ERROR | ACTIVE | Manual intervention + successful sync | Manual |

### 6.2 State Transition Logging

All state transitions must be logged with:

```json
{
  "timestamp": "2026-02-25T12:00:00Z",
  "node_id": "node-uuid",
  "from_state": "OFFLINE",
  "to_state": "QUARANTINE",
  "trigger": "return_after_threshold",
  "metadata": {
    "offline_duration_hours": 96,
    "last_sync_position": 12345678
  }
}
```

---

## 7. Database Schema

### 7.1 Node Table Extensions

```sql
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMP;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS quarantine_entry_time TIMESTAMP;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS quarantine_reason TEXT;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS node_version VARCHAR(32);
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS approved_by INTEGER REFERENCES users(id);
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;
```

### 7.2 Node State History Table

```sql
CREATE TABLE node_state_history (
    id SERIAL PRIMARY KEY,
    node_id BIGINT REFERENCES nodes(id),
    from_state VARCHAR(32),
    to_state VARCHAR(32),
    trigger VARCHAR(64),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_node_state_history_node ON node_state_history(node_id);
CREATE INDEX idx_node_state_history_created ON node_state_history(created_at);
```

---

## 8. API Endpoints

### 8.1 New Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/node-sync/heartbeat` | POST | Heartbeat from sync agent |
| `/api/node-sync/quarantine/{node_id}/approve` | POST | Admin approve quarantined node |
| `/api/node-sync/quarantine/{node_id}/reject` | POST | Admin reject quarantined node |
| `/api/nodes/{node_id}/quarantine` | POST | Manual quarantine |
| `/api/nodes/{node_id}/history` | GET | State transition history |

### 8.2 Modified Endpoints

| Endpoint | Change |
|----------|--------|
| `/api/node-sync/ingest` | Block if node is QUARANTINE |
| `/api/node-sync/config` | Block if node is QUARANTINE |
| `/api/node-sync/register` | Record node_version |

---

## 9. UI Requirements

### 9.1 Node List Page

- Show state with colored indicators
- Filter by state
- Show "last heartbeat" timestamp
- Show "last sync" timestamp
- Quarantine approval actions for admins

### 9.2 Quarantine Queue

- Dedicated view for quarantined nodes
- Show quarantine reason and duration
- Show validation status (version, sync gap)
- Approve/Reject buttons

### 9.3 Alerts

| Alert | Condition |
|-------|-----------|
| Node Stale | Any node in STALE state |
| Node Offline | Any node in OFFLINE state |
| Node Quarantined | Any node enters QUARANTINE |
| Quarantine Pending | Nodes awaiting approval |

---

## 10. Monitoring

### 10.1 Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `pb_nodes_total` | Gauge | Total nodes by state |
| `pb_node_heartbeat_latency_seconds` | Histogram | Heartbeat response time |
| `pb_node_sync_gap` | Gauge | Sync position gap per node |
| `pb_quarantine_queue_size` | Gauge | Nodes awaiting approval |

### 10.2 Dashboards

- Node health overview panel
- State distribution pie chart
- Quarantine queue timeline

---

## 11. Implementation Checklist

- [ ] Add new states to `NodeStatus` enum
- [ ] Create database migration for schema changes
- [ ] Implement heartbeat endpoint
- [ ] Add heartbeat to sync agent
- [ ] Implement state transition logic
- [ ] Add quarantine validation
- [ ] Create approval API endpoints
- [ ] Update node list UI
- [ ] Create quarantine queue UI
- [ ] Add alerts for state changes
- [ ] Add Prometheus metrics
- [ ] Update documentation
