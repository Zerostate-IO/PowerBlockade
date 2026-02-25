# Upgrade and Rollback Validation Playbook

**Document Version**: 1.0  
**Date**: 2026-02-25  
**Status**: Operational Playbook

---

## 1. Overview

This playbook provides step-by-step procedures for upgrading PowerBlockade and validating successful rollback. It ensures data retention settings are preserved and system integrity is maintained.

---

## 2. Pre-Upgrade Checklist

### 2.1 System Health Verification

```bash
# Check current status
./scripts/pb status

# Verify all services healthy
docker compose ps

# Check disk space (need 500MB+)
df -h .
```

### 2.2 Retention Configuration Audit

```bash
# Export current retention settings
docker compose exec postgres psql -U powerblockade -c "
SELECT key, value FROM settings 
WHERE key LIKE 'retention_%';
" > retention-settings-backup.txt

# Verify expected values
cat retention-settings-backup.txt
```

**Expected Settings**:
| Key | Expected Value |
|-----|---------------|
| `retention_query_logs_days` | Per policy (default 15) |
| `retention_node_metrics_days` | Per policy (verify!) |
| `retention_audit_logs_days` | Per policy (default 90) |

### 2.3 Node Status Audit

```bash
# List all nodes and their sync positions
curl -s http://localhost:8080/api/nodes | jq '.[] | {name, status, last_seen}'
```

**Record for comparison after upgrade**:
- Node names
- Current status
- Last sync timestamps

### 2.4 Observability Backup (Manual)

```bash
# Backup Grafana database
docker compose exec grafana sqlite3 /var/lib/grafana/grafana.db ".backup /tmp/grafana-backup.db"
docker compose cp grafana:/tmp/grafana-backup.db backups/grafana-$(date +%Y%m%d).db

# Backup Prometheus data
docker compose exec prometheus tar -czf /tmp/prometheus-backup.tar.gz /prometheus
docker compose cp prometheus:/tmp/prometheus-backup.tar.gz backups/prometheus-$(date +%Y%m%d).tar.gz
```

---

## 3. Upgrade Procedure

### 3.1 Standard Upgrade

```bash
# Run upgrade
./scripts/pb update
```

**This automatically**:
1. ✅ Backs up database (`backups/pre-upgrade-*.sql`)
2. ✅ Backs up config (`.env`, `shared/rpz/`, `shared/forward-zones/`)
3. ✅ Pulls new images
4. ✅ Runs migrations
5. ✅ Restarts services
6. ✅ Verifies health

### 3.2 Upgrade to Specific Version

```bash
./scripts/pb update --to 1.2.0
```

### 3.3 Skip Backup (Not Recommended)

```bash
./scripts/pb update --skip-backup
```

---

## 4. Post-Upgrade Validation

### 4.1 Service Health Check

```bash
# Check all services running
docker compose ps

# Verify health endpoint
curl -sf http://localhost:8080/health

# Check version
curl -s http://localhost:8080/api/version | jq .
```

### 4.2 Retention Settings Verification

```bash
# Compare with pre-upgrade backup
docker compose exec postgres psql -U powerblockade -c "
SELECT key, value FROM settings 
WHERE key LIKE 'retention_%';
" > retention-settings-after.txt

# Diff
diff retention-settings-backup.txt retention-settings-after.txt
```

**Expected**: No differences. If differences exist, investigate migration.

### 4.3 Database Schema Verification

```bash
# Check migration version
docker compose exec admin-ui alembic current

# Expected: latest revision
```

### 4.4 Node Sync Verification

```bash
# Check node status
curl -s http://localhost:8080/api/nodes | jq '.[] | {name, status, last_seen}'

# Compare with pre-upgrade record
# All nodes should show ACTIVE status
# last_seen should be recent
```

### 4.5 Data Integrity Checks

```bash
# Check table counts
docker compose exec postgres psql -U powerblockade -c "
SELECT 
  (SELECT COUNT(*) FROM query_logs) as query_logs,
  (SELECT COUNT(*) FROM node_metrics) as node_metrics,
  (SELECT COUNT(*) FROM audit_logs) as audit_logs,
  (SELECT COUNT(*) FROM blocks) as blocks,
  (SELECT COUNT(*) FROM nodes) as nodes;
"
```

### 4.6 Functional Tests

```bash
# Test DNS resolution
dig @127.0.0.1 example.com

# Test admin UI login
curl -sf http://localhost:8080/

# Test Grafana proxy
curl -sf http://localhost:8080/grafana/
```

---

## 5. Rollback Procedure

### 5.1 Standard Rollback

```bash
# Run rollback with database restore
./scripts/pb rollback
```

**This automatically**:
1. ✅ Reads previous version from state
2. ✅ Prompts for confirmation
3. ✅ Stops services
4. ✅ Restores database from backup
5. ✅ Starts services
6. ✅ Verifies health

### 5.2 Fast Rollback (Schema Compatible Only)

```bash
# Skip database restore - only safe if schema is N-1 compatible
./scripts/pb rollback --fast
```

**Warning**: Use `--fast` only when:
- Schema has not changed between versions
- No data migrations were run
- You're certain data is compatible

### 5.3 Manual Rollback

If `pb rollback` fails:

```bash
# 1. Stop services
docker compose down

# 2. Start postgres only
docker compose up -d postgres
sleep 5

# 3. Find latest backup
ls -lt backups/pre-upgrade-*.sql | head -1

# 4. Restore database
docker compose exec -T postgres psql -U powerblockade -c "
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
"
docker compose exec -T postgres psql -U powerblockade powerblockade < backups/pre-upgrade-TIMESTAMP.sql

# 5. Pull previous images (if needed)
docker compose pull

# 6. Start services
docker compose up -d

# 7. Verify health
./scripts/pb status
```

---

## 6. Post-Rollback Validation

### 6.1 Service Health Check

```bash
# Same as post-upgrade validation
./scripts/pb status
curl -sf http://localhost:8080/health
```

### 6.2 Retention Settings Verification

```bash
# Compare with pre-upgrade backup
docker compose exec postgres psql -U powerblockade -c "
SELECT key, value FROM settings 
WHERE key LIKE 'retention_%';
" > retention-settings-rollback.txt

diff retention-settings-backup.txt retention-settings-rollback.txt
```

**Expected**: No differences. Rollback should restore exact state.

### 6.3 Data Integrity Checks

```bash
# Check table counts match pre-upgrade
docker compose exec postgres psql -U powerblockade -c "
SELECT 
  (SELECT COUNT(*) FROM query_logs) as query_logs,
  (SELECT COUNT(*) FROM node_metrics) as node_metrics,
  (SELECT COUNT(*) FROM audit_logs) as audit_logs;
"
```

### 6.4 Observability State Check

**Note**: Observability volumes (Grafana, Prometheus) are NOT automatically restored.

```bash
# Check if manual restore needed
ls -la backups/grafana-*.db 2>/dev/null
ls -la backups/prometheus-*.tar.gz 2>/dev/null

# If backups exist and restore needed:
# Grafana restore
docker compose cp backups/grafana-TIMESTAMP.db grafana:/var/lib/grafana/grafana.db
docker compose restart grafana

# Prometheus restore
docker compose cp backups/prometheus-TIMESTAMP.tar.gz prometheus:/tmp/
docker compose exec prometheus tar -xzf /tmp/prometheus-TIMESTAMP.tar.gz -C /
docker compose restart prometheus
```

---

## 7. Failure Scenarios

### 7.1 Migration Fails

**Symptoms**: `alembic upgrade head` returns error

**Recovery**:
```bash
# Do NOT restart services
# Database is in unknown state

# 1. Check migration status
docker compose exec admin-ui alembic current

# 2. Review migration error
docker compose logs admin-ui

# 3. If recoverable, fix and retry
docker compose exec admin-ui alembic upgrade head

# 4. If not recoverable, rollback
./scripts/pb rollback
```

### 7.2 Services Won't Start

**Symptoms**: `docker compose up -d` fails

**Recovery**:
```bash
# Check logs
docker compose logs

# Common issues:
# - Port conflicts: lsof -i :8080
# - Volume issues: docker volume ls
# - Permission issues: ls -la shared/

# Force recreate
docker compose down
docker compose up -d --force-recreate
```

### 7.3 Database Restore Fails

**Symptoms**: `psql` restore errors

**Recovery**:
```bash
# Try with single transaction
docker compose exec -T postgres psql -U powerblockade -1 -f backups/pre-upgrade-*.sql powerblockade

# If still failing, check backup integrity
head -20 backups/pre-upgrade-*.sql
tail -20 backups/pre-upgrade-*.sql

# Last resort: start fresh
docker compose down -v  # WARNING: deletes all data
docker compose up -d
```

### 7.4 Nodes Show ERROR After Rollback

**Symptoms**: Node status is ERROR or sync fails

**Recovery**:
```bash
# Check sync positions
curl -s http://localhost:8080/api/nodes | jq '.[] | {name, status}'

# May need to reset sync position on node
# (On sync agent)
rm -f /var/lib/powerblockade/sync-state.db
systemctl restart powerblockade-sync
```

---

## 8. Validation Checklist

### Pre-Upgrade
- [ ] System health verified
- [ ] Retention settings exported
- [ ] Node status recorded
- [ ] Observability backed up (optional)

### Post-Upgrade
- [ ] All services healthy
- [ ] Retention settings unchanged
- [ ] Schema version correct
- [ ] Nodes syncing normally
- [ ] Data integrity verified
- [ ] DNS resolution working
- [ ] Admin UI accessible
- [ ] Grafana accessible

### Post-Rollback
- [ ] All services healthy
- [ ] Retention settings restored
- [ ] Data counts match pre-upgrade
- [ ] Observability state acceptable

---

## 9. Rollback Decision Matrix

| Symptom | Severity | Action |
|---------|----------|--------|
| Migration failure | Critical | Rollback immediately |
| Data integrity failure | Critical | Rollback immediately |
| Service won't start | High | Debug first, rollback if unresolved |
| Minor feature broken | Medium | Fix forward if possible |
| Performance regression | Low | Monitor, rollback if severe |

---

## 10. Communication Template

### Upgrade Notification

```
PowerBlockade Upgrade Notice

Date: [DATE]
Time: [TIME]
Duration: ~15 minutes

What: Upgrading PowerBlockade from vX.Y.Z to vA.B.C

Impact:
- DNS resolution will continue during upgrade
- Admin UI will be unavailable briefly
- No data loss expected

Questions: [CONTACT]
```

### Rollback Notification

```
PowerBlockade Rollback Notice

Date: [DATE]
Time: [TIME]
Reason: [REASON]

Action: Rolling back from vX.Y.Z to vA.B.C

Data Status:
- Database restored to pre-upgrade state
- All data preserved

Questions: [CONTACT]
```
