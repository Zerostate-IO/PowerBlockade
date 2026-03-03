# Upgrade and Rollback Validation Playbook

**Document Version**: 2.0
**Date**: 2026-03-03
**Status**: Operational Playbook

---

## Overview

This playbook provides deterministic pre-flight, in-flight, and post-flight checks for PowerBlockade upgrades and rollbacks. Every check includes a command, expected output, and fail action.

**Key Principles**:
- Never upgrade without capturing baseline state
- Every migration is a potential rollback point
- Drift detection catches data/observability misalignment
- Rollback rehearsals validate recovery procedures

---

## 1. Pre-Flight Checklist

Run these checks before ANY upgrade. All ABORT-level checks must pass.

### 1.1 Service Health Baseline

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| All services healthy | `./scripts/pb doctor` | "All checks passed" | **ABORT** |
| PostgreSQL reachable | `docker compose -f docker-compose.ghcr.yml exec -T postgres pg_isready -U powerblockade` | "accepting connections" | **ABORT** |
| Admin UI responding | `curl -sf http://localhost:8080/health` | HTTP 200, "healthy" | **ABORT** |
| DNS resolution works | `dig @127.0.0.1 google.com +short` | Returns IP address | **WARN** |

### 1.2 Database State Capture

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Row counts baseline | See command block below | Table counts returned | **ABORT** |
| Date ranges baseline | See command block below | Min/max dates returned | **ABORT** |
| Migration status | `docker compose -f docker-compose.ghcr.yml exec -T admin-ui alembic current` | Shows current revision | **ABORT** |

**Row Counts Baseline Command**:
```bash
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "
SELECT 'dns_query_events' as tbl, count(*) FROM dns_query_events
UNION ALL SELECT 'query_rollups', count(*) FROM query_rollups
UNION ALL SELECT 'node_metrics', count(*) FROM node_metrics
UNION ALL SELECT 'blocklists', count(*) FROM blocklists
UNION ALL SELECT 'manual_entries', count(*) FROM manual_entries
UNION ALL SELECT 'nodes', count(*) FROM nodes;
" > /tmp/pre-upgrade-row-counts.txt
```

**Date Ranges Baseline Command**:
```bash
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "
SELECT 'dns_query_events', min(ts)::date, max(ts)::date FROM dns_query_events
UNION ALL SELECT 'query_rollups', min(bucket_start)::date, max(bucket_start)::date FROM query_rollups
UNION ALL SELECT 'node_metrics', min(ts)::date, max(ts)::date FROM node_metrics;
" > /tmp/pre-upgrade-date-ranges.txt
```

### 1.3 Retention Settings Capture

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Retention config | See command below | retention_% keys returned | **ABORT** |
| Values in range | Manual inspection | 7-90 days events, 30-730 rollups | **WARN** |

```bash
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "
SELECT key, value FROM settings WHERE key LIKE 'retention_%';
" > /tmp/pre-upgrade-retention-settings.txt
```

### 1.4 Config State Capture

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Blocklist state | See command below | Blocklist rows returned | **CONTINUE** |
| Forward zones | See command below | Zone rows returned | **CONTINUE** |

```bash
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "
SELECT id, name, enabled, list_type, last_updated FROM blocklists ORDER BY id;
" > /tmp/pre-upgrade-blocklists.txt

docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "
SELECT * FROM forward_zones;
" > /tmp/pre-upgrade-forward-zones.txt
```

### 1.5 Observability Baseline

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Prometheus metrics | `curl -s http://localhost:8080/metrics > /tmp/pre-upgrade-metrics.txt` | Non-empty file | **WARN** |
| Key metrics present | `grep -E "powerblockade_queries_total\|powerblockade_blocked_total" /tmp/pre-upgrade-metrics.txt` | Metric lines found | **WARN** |
| Grafana healthy | `curl -sf http://localhost:8080/grafana/api/health` | "ok" response | **WARN** |

### 1.6 Disk Space and Backup

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Disk space | `df -h . \| awk 'NR==2 {print $4}'` | >= 500MB available | **ABORT** |
| Backup directory | `ls shared/backups/` | Directory exists | **ABORT** |
| Create backup | `./scripts/pb backup` | "Backup created" | **ABORT** |
| Backup valid | `head -5 shared/backups/pre-upgrade-*.sql \| tail -1` | PostgreSQL dump header | **ABORT** |

### 1.7 Dry-Run Check (Optional)

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Pull images only | `docker compose -f docker-compose.ghcr.yml pull` | Images pulled, no errors | **WARN** |
| Check pending migrations | `docker compose -f docker-compose.ghcr.yml exec -T admin-ui alembic history --verbose \| head -20` | Shows migration history | **CONTINUE** |

---

## 2. In-Flight Monitoring

Watch these indicators during the upgrade process.

### 2.1 Upgrade Execution

```bash
# Start upgrade
./scripts/pb update
```

### 2.2 Real-Time Monitoring Commands

| What to Monitor | Command | Normal Indicator | Problem Indicator |
|-----------------|---------|------------------|-------------------|
| Container status | `watch -n 2 'docker compose -f docker-compose.ghcr.yml ps'` | Containers starting | Repeated restarts |
| Migration logs | `docker compose -f docker-compose.ghcr.yml logs -f admin-ui 2>&1 \| grep -E "alembic\|migration"` | "Running upgrade" | Error messages |
| Database connections | `docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -c "SELECT count(*) FROM pg_stat_activity;"` | Low connection count | Connections climbing |
| Disk I/O | `iostat -x 2 2` | Moderate util | 100% util sustained |

### 2.3 Timeout Thresholds

| Stage | Max Duration | Action if Exceeded |
|-------|--------------|-------------------|
| Image pull | 5 minutes | Check network, retry |
| Database backup | 10 minutes | Check disk I/O |
| Migration run | 5 minutes | Check migration logs |
| Service restart | 2 minutes | Check container logs |

---

## 3. Post-Flight Verification

Run these checks immediately after upgrade completes.

### 3.1 Service Health Verification

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| All services up | `docker compose -f docker-compose.ghcr.yml ps` | All "running" or "healthy" | **ABORT → ROLLBACK** |
| Health endpoint | `curl -sf http://localhost:8080/health` | HTTP 200 | **ABORT → ROLLBACK** |
| Version check | `./scripts/pb version` | New version displayed | **WARN** |
| API version | `curl -s http://localhost:8080/api/version \| jq .` | JSON with new version | **WARN** |

### 3.2 Database Continuity Verification

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Migration current | `docker compose -f docker-compose.ghcr.yml exec -T admin-ui alembic current` | Latest revision | **ABORT → ROLLBACK** |
| Row counts compare | `diff /tmp/pre-upgrade-row-counts.txt <(docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "SELECT 'dns_query_events', count(*) FROM dns_query_events UNION ALL SELECT 'query_rollups', count(*) FROM query_rollups UNION ALL SELECT 'node_metrics', count(*) FROM node_metrics UNION ALL SELECT 'blocklists', count(*) FROM blocklists UNION ALL SELECT 'manual_entries', count(*) FROM manual_entries UNION ALL SELECT 'nodes', count(*) FROM nodes;")` | No diff (or minor +delta) | **WARN** |
| Date ranges preserved | `diff /tmp/pre-upgrade-date-ranges.txt <(docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "SELECT 'dns_query_events', min(ts)::date, max(ts)::date FROM dns_query_events UNION ALL SELECT 'query_rollups', min(bucket_start)::date, max(bucket_start)::date FROM query_rollups UNION ALL SELECT 'node_metrics', min(ts)::date, max(ts)::date FROM node_metrics;")` | Same min dates | **ABORT → ROLLBACK** |
| Retention preserved | `diff /tmp/pre-upgrade-retention-settings.txt <(docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "SELECT key, value FROM settings WHERE key LIKE 'retention_%';")` | No diff | **WARN** |

### 3.3 Functional Verification

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| DNS resolution | `dig @127.0.0.1 google.com +short` | Returns IP | **ABORT → ROLLBACK** |
| Blocking works | `dig @127.0.0.1 doubleclick.net +short` | 0.0.0.0 or NXDOMAIN | **WARN** |
| Query ingestion | See command block below | Event appears in DB | **WARN** |
| Admin UI login | `curl -sf http://localhost:8080/` | HTTP 200, HTML returned | **WARN** |
| Grafana proxy | `curl -sf http://localhost:8080/grafana/api/health` | "ok" response | **WARN** |

**Query Ingestion Test**:
```bash
# Generate test query
dig @127.0.0.1 post-upgrade-test-$(date +%s).example.com

# Wait for ingestion
sleep 5

# Verify event appears
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "
SELECT * FROM dns_query_events 
WHERE qname LIKE '%post-upgrade-test%' 
ORDER BY ts DESC LIMIT 1;
"
```

### 3.4 Observability Alignment

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Metrics endpoint | `curl -s http://localhost:8080/metrics > /tmp/post-upgrade-metrics.txt` | Non-empty file | **WARN** |
| Metrics comparable | `grep -E "powerblockade_queries_total" /tmp/post-upgrade-metrics.txt` | Value near pre-upgrade | **WARN** |
| Prometheus targets | `curl -s http://localhost:9090/api/v1/targets \| jq '.data.activeTargets[].health'` | "up" status | **WARN** |
| Grafana dashboards | `curl -sf http://localhost:8080/grafana/api/search` | JSON array of dashboards | **WARN** |

---

## 4. Rollback Procedure

### 4.1 Pre-Rollback Assessment

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| State file exists | `cat .pb-state.json \| jq .` | Valid JSON with versions | **ABORT** |
| Backup file exists | `ls -la $(jq -r '.last_db_backup' .pb-state.json)` | File listed with size | **ABORT** |
| Backup integrity | `file $(jq -r '.last_db_backup' .pb-state.json)` | "PostgreSQL..." | **ABORT** |

### 4.2 Standard Rollback

```bash
# Execute rollback with database restore
./scripts/pb rollback
```

This automatically:
1. Reads previous version from `.pb-state.json`
2. Prompts for confirmation
3. Stops services
4. Restores database from backup
5. Starts services on previous version
6. Verifies health

### 4.3 Fast Rollback (Schema Compatible Only)

```bash
# Skip database restore - only if schema unchanged
./scripts/pb rollback --fast
```

**Prerequisites for --fast**:
- Schema has not changed between versions
- No data migrations were run
- You're certain data is compatible

### 4.4 Manual Rollback (If pb rollback Fails)

```bash
# 1. Stop all services
docker compose -f docker-compose.ghcr.yml down

# 2. Start postgres only
docker compose -f docker-compose.ghcr.yml up -d postgres
sleep 5

# 3. Find latest backup
BACKUP_FILE=$(ls -t shared/backups/pre-upgrade-*.sql 2>/dev/null | head -1)

# 4. Restore database
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -c "
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
"
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade powerblockade < "$BACKUP_FILE"

# 5. Pull previous images (if needed)
docker compose -f docker-compose.ghcr.yml pull

# 6. Start services
docker compose -f docker-compose.ghcr.yml up -d

# 7. Verify
./scripts/pb doctor
```

---

## 5. Post-Rollback Verification

### 5.1 Service Health

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| All services up | `docker compose -f docker-compose.ghcr.yml ps` | All "running" or "healthy" | **DEBUG** |
| Health endpoint | `curl -sf http://localhost:8080/health` | HTTP 200 | **DEBUG** |
| Version reverted | `./scripts/pb version` | Previous version | **WARN** |

### 5.2 Data Integrity After Rollback

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Row counts match | Compare with `/tmp/pre-upgrade-row-counts.txt` | Same or earlier timestamp | **WARN** |
| Retention settings | `diff /tmp/pre-upgrade-retention-settings.txt <(docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "SELECT key, value FROM settings WHERE key LIKE 'retention_%';")` | No diff | **WARN** |
| Date ranges match | Compare with `/tmp/pre-upgrade-date-ranges.txt` | Same min dates | **WARN** |

### 5.3 Functional Verification After Rollback

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| DNS resolution | `dig @127.0.0.1 google.com +short` | Returns IP | **DEBUG** |
| Blocking works | `dig @127.0.0.1 doubleclick.net +short` | 0.0.0.0 or NXDOMAIN | **WARN** |
| Query ingestion | `dig @127.0.0.1 rollback-test.example.com && sleep 5 && docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "SELECT count(*) FROM dns_query_events WHERE qname LIKE '%rollback-test%';"` | count >= 1 | **WARN** |

---

## 6. Drift Detection

Detect misalignment between database state and observability systems.

### 6.1 Schema Drift

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Alembic check | `docker compose -f docker-compose.ghcr.yml exec -T admin-ui alembic check` | "No problems detected" | **WARN** |
| Table existence | `docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"` | Expected tables listed | **ABORT** |

### 6.2 Data Drift

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Orphaned metrics | See command below | count = 0 | **WARN** |
| Rollup continuity | See command below | No gaps > 2 hours | **WARN** |
| Node alignment | See command below | All nodes have recent metrics | **WARN** |

**Orphaned Metrics Check**:
```bash
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "
SELECT count(*) as orphaned_metrics FROM node_metrics m
WHERE NOT EXISTS (SELECT 1 FROM nodes n WHERE n.id = m.node_id);
"
```

**Rollup Continuity Check**:
```bash
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "
SELECT 
  date_trunc('hour', bucket_start) as hour,
  count(*) as rollup_count
FROM query_rollups
WHERE bucket_start > now() - interval '24 hours'
GROUP BY date_trunc('hour', bucket_start)
ORDER BY hour;
"
```

**Node Alignment Check**:
```bash
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "
SELECT 
  n.name as node_name,
  count(m.id) as metrics_count,
  max(m.ts) as latest_metric
FROM nodes n
LEFT JOIN node_metrics m ON n.id = m.node_id
GROUP BY n.name
ORDER BY n.name;
"
```

### 6.3 Observability vs Database Drift

| Check | Command | Expected Output | Fail Action |
|-------|---------|-----------------|-------------|
| Prometheus vs DB count | Compare `powerblockade_queries_total` with `SELECT count(*) FROM dns_query_events WHERE ts > now() - interval '24 hours'` | Within 5% | **WARN** |
| Grafana data source | `curl -s http://localhost:8080/grafana/api/datasources \| jq '.[].name'` | postgres datasource exists | **WARN** |

---

## 7. Rollback Rehearsal Procedure

Practice rollback before you need it for real.

### 7.1 Pre-Rehearsal Checklist

| Step | Command | Notes |
|------|---------|-------|
| 1. Create fresh backup | `./scripts/pb backup` | Rehearsal will test restore |
| 2. Note current version | `./scripts/pb version > /tmp/rehearsal-version.txt` | For comparison |
| 3. Capture row counts | See pre-flight section | Baseline for verification |

### 7.2 Rehearsal Execution

```bash
# 1. Simulate upgrade issue (stop admin-ui only)
docker compose -f docker-compose.ghcr.yml stop admin-ui

# 2. Execute rollback
./scripts/pb rollback

# 3. Verify services restored
./scripts/pb doctor

# 4. Verify data integrity
# Run post-rollback verification section

# 5. Document results
echo "Rehearsal completed: $(date)" >> /tmp/rollback-rehearsal.log
```

### 7.3 Rehearsal Success Criteria

- [ ] Rollback command completes without error
- [ ] All services return to healthy state
- [ ] Row counts match pre-rehearsal baseline
- [ ] DNS resolution works after rollback
- [ ] Version matches pre-rehearsal version

---

## 8. Quick Reference: Copy-Paste Commands

### Pre-Flight One-Liner

```bash
./scripts/pb doctor && \
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "SELECT 'dns_query_events', count(*) FROM dns_query_events UNION ALL SELECT 'query_rollups', count(*) FROM query_rollups UNION ALL SELECT 'node_metrics', count(*) FROM node_metrics;" > /tmp/pre-upgrade-row-counts.txt && \
curl -s http://localhost:8080/metrics > /tmp/pre-upgrade-metrics.txt && \
./scripts/pb backup && \
echo "Pre-flight complete. Ready for: ./scripts/pb update"
```

### Post-Flight One-Liner

```bash
./scripts/pb doctor && \
docker compose -f docker-compose.ghcr.yml exec -T admin-ui alembic current && \
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -d powerblockade -c "SELECT 'dns_query_events', count(*) FROM dns_query_events UNION ALL SELECT 'query_rollups', count(*) FROM query_rollups UNION ALL SELECT 'node_metrics', count(*) FROM node_metrics;" > /tmp/post-upgrade-row-counts.txt && \
curl -s http://localhost:8080/metrics > /tmp/post-upgrade-metrics.txt && \
diff /tmp/pre-upgrade-row-counts.txt /tmp/post-upgrade-row-counts.txt && \
echo "Post-flight complete."
```

### Rollback One-Liner

```bash
cat .pb-state.json | jq '{current, previous, backup: .last_db_backup}' && \
ls -la $(jq -r '.last_db_backup' .pb-state.json) && \
./scripts/pb rollback
```

---

## 9. Failure Scenario Decision Matrix

| Symptom | Severity | Action | Rollback? |
|---------|----------|--------|-----------|
| Migration failure | Critical | Check logs, rollback if unrecoverable | Yes |
| Data integrity failure | Critical | Immediate rollback | Yes |
| Services won't start | High | Debug 5 min, then rollback | Likely |
| Retention settings lost | Medium | Manually restore from backup | No |
| Minor feature broken | Medium | Fix forward if possible | No |
| Performance regression | Low | Monitor, rollback if severe | Maybe |
| Observability gap | Low | Manual Prometheus/Grafana restore | No |

---

## 10. State Files Reference

| File | Purpose | Retention |
|------|---------|-----------|
| `.pb-state.json` | Current/previous version, last backup path | Indefinite |
| `shared/backups/pre-upgrade-*.sql` | Database dumps before upgrades | 5 backups |
| `shared/backups/config-*.tar.gz` | Config snapshots | 5 backups |
| `/tmp/pre-upgrade-*.txt` | Baseline captures for comparison | Session only |

---

## 11. Communication Templates

### Upgrade Notification

```
PowerBlockade Upgrade Notice

Date: [DATE]
Time: [TIME]
Expected Duration: ~15 minutes

What: Upgrading from vX.Y.Z to vA.B.C

Impact:
- DNS resolution continues during upgrade
- Admin UI briefly unavailable
- No data loss expected

Rollback Plan: Pre-upgrade backup at shared/backups/pre-upgrade-[TIMESTAMP].sql
```

### Rollback Notification

```
PowerBlockade Rollback Notice

Date: [DATE]
Time: [TIME]
Reason: [REASON]

Action: Rolled back from vX.Y.Z to vA.B.C

Data Status:
- Database restored to pre-upgrade state
- All data preserved as of backup timestamp
- Observability may have gaps during upgrade window
```
