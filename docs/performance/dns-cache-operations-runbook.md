# DNS Cache Operations Runbook: Regression Gates

This document defines objective gate thresholds for promoting DNS caching changes. All gates must pass for promotion; no single metric (especially QPS gains) justifies promotion if any observability or data integrity gate fails.

---

## Overview

### Purpose
Codify objective, measurable thresholds for:
- **Performance gates**: latency, QPS, cache hit ratio
- **Observability gates**: external query completeness, internal container exclusion
- **Parity gates**: event ingest count, metric value consistency
- **Block promotion conditions**: what failures prevent promotion

### Promotion Philosophy
```
+---------------------------------------------------------------------+
|                    PROMOTION DECISION TREE                          |
+---------------------------------------------------------------------+
|                                                                     |
|  1. OBSERVABILITY GATES -----------------------------------------> |
|     |                                                               |
|     +- FAIL -> BLOCK PROMOTION                                   |
|     |         (data integrity compromised)                          |
|     |                                                               |
|     +- PASS -----------------------------------------------------> |
|                                                                     |
|  2. PARITY GATES -------------------------------------------------> |
|     |                                                               |
|     +- FAIL -> BLOCK PROMOTION                                   |
|     |         (behavioral regression)                               |
|     |                                                               |
|     +- PASS -----------------------------------------------------> |
|                                                                     |
|  3. PERFORMANCE GATES -------------------------------------------> |
|     |                                                               |
|     +- FAIL (within tolerance) -> WARN, ALLOW WITH DOCUMENTATION |
|     |                                                               |
|     +- FAIL (exceeds tolerance) -> BLOCK PROMOTION               |
|     |                                                               |
|     +- PASS -----------------------------------------------------> |
|                                                                     |
|  4. ALL PASS -> ALLOW PROMOTION                                  |
|                                                                     |
+---------------------------------------------------------------------+
```

---

## Performance Gates

### Latency Thresholds

| Phase | Metric | Threshold | Block If | Source |
|-------|--------|-----------|----------|--------|
| Cold Cache | `p50_latency_ms` | < 20ms | > 25ms (+25%) | `dns-benchmark-methodology.md` |
| Cold Cache | `p95_latency_ms` | < 100ms | > 125ms (+25%) | `dns-benchmark-methodology.md` |
| Cold Cache | `p99_latency_ms` | < 200ms | > 250ms (+25%) | `dns-benchmark-methodology.md` |
| Warm Cache | `p50_latency_ms` | < 5ms | > 6.25ms (+25%) | `dns-benchmark-methodology.md` |
| Warm Cache | `p95_latency_ms` | < 20ms | > 25ms (+25%) | `dns-benchmark-methodology.md` |
| Warm Cache | `p99_latency_ms` | < 50ms | > 62.5ms (+25%) | `dns-benchmark-methodology.md` |
| Any | Latency distribution | >= 70% under 50ms | < 50% under 50ms | `test-e2e.sh:569-576` |

**Formulas**:
```
p50_latency_ms = percentile(queries.latency_ms, 0.50)
p95_latency_ms = percentile(queries.latency_ms, 0.95)
p99_latency_ms = percentile(queries.latency_ms, 0.99)

latency_distribution_pass = (
    count(queries WHERE latency_ms < 50) / count(queries)
) >= 0.70
```

### QPS Thresholds

| Phase | Metric | Minimum | Block If | Source |
|-------|--------|---------|----------|--------|
| Cold Cache | `qps_actual` | > 500 | < 400 (-20%) | `dns-benchmark-methodology.md` |
| Warm Cache | `qps_actual` | > 4000 | < 3200 (-20%) | `dns-benchmark-methodology.md` |
| Saturation | `max_qps_sustained` | > 5000 | < 4000 (-20%) | `dns-benchmark-methodology.md` |
| Saturation | `error_rate_pct` | < 5% | > 10% | `dns-benchmark-methodology.md` |

**Formulas**:
```
qps_actual = queries_completed / duration_seconds

max_qps_sustained = max(qps WHERE queries_lost_rate < 5%)

error_rate_pct = (queries_lost / queries_sent) * 100
```

**IMPORTANT**: QPS gains alone do NOT justify promotion. A 50% QPS improvement with 1% data loss is a BLOCK.

### Cache Hit Ratio Thresholds

| Phase | Metric | Minimum | Warning | Critical | Source |
|-------|--------|---------|---------|----------|--------|
| Warm Cache | `cache_hit_ratio` | > 90% | < 80% | < 50% | `dns-benchmark-methodology.md`, `alerts.yml:4-16` |
| Any | `recursor_cache_hit_rate` | > 50% | < 50% (10m) | < 20% (5m) | `prometheus/alerts.yml` |

**Formulas**:
```
# From metrics.py:84-86
cache_hit_ratio = (cache_hits / total_queries) * 100

# Cache hit proxy (from metrics.py:77-80)
# Queries with latency < 5ms are assumed cache hits
cache_hits_proxy = count(queries WHERE latency_ms < 5 AND blocked = false)

# From recursor statistics
recursor_hit_rate = (
    cache_hits / (cache_hits + cache_misses)
) * 100
```

**Alerting thresholds** (from `prometheus/alerts.yml`):
```yaml
# Warning: Cache hit rate < 50% for 10 minutes
LowCacheHitRate:
  expr: (cache_hits / (cache_hits + cache_misses)) * 100 < 50
  for: 10m

# Critical: Cache hit rate < 20% for 5 minutes
CriticalCacheHitRate:
  expr: (cache_hits / (cache_hits + cache_misses)) * 100 < 20
  for: 5m
```

---

## Observability Gates

These gates are **mandatory** and **block promotion** on any failure.

### External Query Completeness
Ensures no external client queries are dropped from the observability pipeline.

| Metric | Threshold | Block If |
|--------|-----------|----------|
| External query capture rate | 100% | < 99.9% |
| External query latency attribution | 100% | < 99.9% |

**Formula**:
```
external_completeness_rate = (
    count(ingested_events WHERE client_ip NOT IN docker_subnet) /
    count(dnsdist_responses WHERE client_ip NOT IN docker_subnet)
) * 100

REQUIREMENT: external_completeness_rate >= 99.9%
```

**Verification query**:
```sql
-- Check for gaps in external client events
SELECT 
    date_trunc('hour', ts) AS hour,
    COUNT(*) AS external_events,
    COUNT(*) FILTER (WHERE client_ip NOT <<= '172.30.0.0/24') AS truly_external
FROM dns_query_events
WHERE ts > now() - interval '24 hours'
GROUP BY hour
HAVING COUNT(*) FILTER (WHERE client_ip NOT <<= '172.30.0.0/24') = 0;
-- Should return 0 rows (no gaps)
```

### Internal Container Exclusion
Ensures internal Docker traffic is correctly excluded from display metrics.

| Metric | Threshold | Block If |
|--------|-----------|----------|
| Internal in display queries | 0 | > 0 |
| Internal in rollup aggregations | 0 | > 0 |
| Internal in Prometheus exports | 0 | > 0 |

**Network boundary** (from `dns-query-path-and-observability.md`):
```
DOCKER_SUBNET = 172.30.0.0/24  # Default, configurable via compose.yaml

Classification:
  IF client_ip IN DOCKER_SUBNET -> INTERNAL_CONTAINER (exclude)
  ELSE -> EXTERNAL_CLIENT (include)

NOTE: RFC 1918 addresses (10.x, 172.16-31.x, 192.168.x) are EXTERNAL clients.
Only the Docker subnet represents internal traffic.
```

**Verification queries**:
```sql
-- 1. Ingest layer: Verify is_internal flag accuracy
SELECT COUNT(*) AS misclassified
FROM dns_query_events
WHERE 
    (client_ip <<= '172.30.0.0/24' AND is_internal = false)
    OR (client_ip NOT <<= '172.30.0.0/24' AND is_internal = true);
-- Should return 0

-- 2. Display layer: Verify UI queries exclude internal
-- (Run this against actual analytics endpoint responses)
-- Expected: No internal IPs in response data

-- 3. Metrics layer: Verify Prometheus exports exclude internal
-- (Check metrics endpoint response)
-- Expected: powerblockade_* metrics do not count internal traffic
```

**Metrics export verification** (from `metrics.py:40-47`):
```python
# Expected filter in metrics queries
stmt = select(func.count()).select_from(DNSQueryEvent).where(
    DNSQueryEvent.ts >= since,
    DNSQueryEvent.is_internal.is_(False),  # MUST exclude internal
)
```

---

## Parity Gates

### Event Ingest Parity
Compares event counts before and after changes to ensure no data loss.

| Metric | Tolerance | Block If |
|--------|-----------|----------|
| Event count delta | +/-5% | > +/-10% |
| Unique domain delta | +/-5% | > +/-10% |
| Unique client delta | +/-5% | > +/-10% |

**Formula**:
```
event_parity_ratio = (
    count(events_after) / count(events_baseline)
)

REQUIREMENT: 0.95 <= event_parity_ratio <= 1.05 (within tolerance)
BLOCK IF: event_parity_ratio < 0.90 OR event_parity_ratio > 1.10
```

**Verification**:
```bash
# Run baseline measurement
baseline_count=$(psql -t -c "SELECT COUNT(*) FROM dns_query_events WHERE ts > now() - interval '1 hour'")

# Apply changes, wait 1 hour, compare
after_count=$(psql -t -c "SELECT COUNT(*) FROM dns_query_events WHERE ts > now() - interval '1 hour'")

# Calculate ratio
ratio=$(echo "scale=4; $after_count / $baseline_count" | bc)
echo "Event parity ratio: $ratio (expected: 0.95-1.05)"
```

### Metric Value Parity
Compares Prometheus metric values before and after changes.

| Metric | Tolerance | Block If |
|--------|-----------|----------|
| `powerblockade_queries_total` | +/-5% | > +/-10% |
| `powerblockade_blocked_total` | +/-5% | > +/-10% |
| `powerblockade_cache_hit_rate` | +/-3pp | > +/-5pp |
| `powerblockade_qps` | +/-5% | > +/-10% |

**Formula**:
```
metric_delta_percent = ((value_after - value_baseline) / value_baseline) * 100

REQUIREMENT: |metric_delta_percent| <= 5% (within tolerance)
BLOCK IF: |metric_delta_percent| > 10%
```

---

## Block Promotion Conditions
The following conditions **always block promotion**, regardless of other positive metrics:

### Mandatory Block Conditions

| Condition | Check | Action |
|-----------|-------|--------|
| **Observability gate failure** | Any external query lost OR internal in display | BLOCK |
| **Ingest parity failure** | Event count delta > 10% | BLOCK |
| **Metrics parity failure** | Any metric delta > 10% | BLOCK |
| **New error types** | Error in after run not in baseline | BLOCK |
| **Error rate increase** | Error rate increased > 5pp | BLOCK |
| **SERVFAIL spike** | SERVFAIL rate > 5% (from `alerts.yml:32-44`) | BLOCK |
| **Timeout spike** | Timeout rate > 2% (from `alerts.yml:46-58`) | BLOCK |

### Performance Block Conditions

| Condition | Check | Action |
|-----------|-------|--------|
| **Latency regression > 25%** | Any percentile exceeds threshold by > 25% | BLOCK |
| **QPS regression > 20%** | Sustained QPS drops by > 20% | BLOCK |
| **Cache hit ratio regression** | Cache hit drops below 50% for 10min | BLOCK |
| **Latency distribution failure** | < 50% queries under 50ms | BLOCK |

### Warning Conditions (Allow with Documentation)

| Condition | Check | Action |
|-----------|-------|--------|
| **Latency regression 15-25%** | Threshold exceeded but within tolerance | WARN |
| **QPS regression 10-20%** | QPS dropped but within tolerance | WARN |
| **Cache hit ratio 50-80%** | Below target but not critical | WARN |

---

## Gate Evaluation Procedure

### Pre-Promotion Checklist

```bash
#!/bin/bash
# scripts/regression-gate-check.sh
# Exit 0 = PASS, Exit 1 = BLOCK, Exit 2 = WARN

set -e

echo "=== PowerBlockade Regression Gate Check ==="
echo ""

GATES_PASSED=0
GATES_WARNED=1
GATES_FAILED=0

# ============================================
# 1. OBSERVABILITY GATES (mandatory)
# ============================================
echo "## 1. Observability Gates"

# 1a. External query completeness
external_completeness=$(psql -t -c "
    SELECT 
        COUNT(*) FILTER (WHERE client_ip NOT <<= '172.30.0.0/24')::float / 
        NULLIF(COUNT(*), 0) * 100
    FROM dns_query_events 
    WHERE ts > now() - interval '1 hour'
" | tr -d ' ')

if (( $(echo "$external_completeness >= 99.9" | bc -l) )); then
    echo "  PASS: External completeness: ${external_completeness}%"
    ((GATES_PASSED++))
else
    echo "  BLOCK: External completeness ${external_completeness}% < 99.9%"
    ((GATES_FAILED++))
fi

# 1b. Internal exclusion
internal_in_display=$(psql -t -c "
    SELECT COUNT(*) 
    FROM dns_query_events 
    WHERE ts > now() - interval '1 hour'
      AND client_ip <<= '172.30.0.0/24'
      AND is_internal = false
" | tr -d ' ')

if [[ "$internal_in_display" -eq 0 ]]; then
    echo "  PASS: Internal exclusion: $internal_in_display internal in display"
    ((GATES_PASSED++))
else
    echo "  BLOCK: $internal_in_display internal queries in display"
    ((GATES_FAILED++))
fi

# ============================================
# 2. PARITY GATES (mandatory)
# ============================================
echo ""
echo "## 2. Parity Gates"

# Requires baseline metrics file
if [[ -f "baseline-event-count.txt" ]]; then
    baseline_count=$(cat baseline-event-count.txt)
    current_count=$(psql -t -c "
        SELECT COUNT(*) FROM dns_query_events 
        WHERE ts > now() - interval '1 hour'
    " | tr -d ' ')
    
    parity_ratio=$(echo "scale=4; $current_count / $baseline_count" | bc)
    
    if (( $(echo "$parity_ratio >= 0.95 && $parity_ratio <= 1.05" | bc -l) )); then
        echo "  PASS: Event parity: ${parity_ratio}"
        ((GATES_PASSED++))
    elif (( $(echo "$parity_ratio < 0.90 || $parity_ratio > 1.10" | bc -l) )); then
        echo "  BLOCK: Event parity ${parity_ratio} outside 0.90-1.10"
        ((GATES_FAILED++))
    else
        echo "  WARN: Event parity ${parity_ratio} outside ideal range"
        ((GATES_WARNED++))
    fi
else
    echo "  WARN: No baseline-event-count.txt found"
fi

# ============================================
# 3. PERFORMANCE GATES
# ============================================
echo ""
echo "## 3. Performance Gates"

# Check Prometheus alerts firing
high_latency=$(curl -s http://localhost:9090/api/v1/alerts | \
    jq -r '.data.alerts[] | select(.labels.alertname == "HighQueryLatency") | .state' 2>/dev/null || echo "")

if [[ -z "$high_latency" ]]; then
    echo "  PASS: No high latency alerts"
    ((GATES_PASSED++))
else
    echo "  BLOCK: HighQueryLatency alert firing"
    ((GATES_FAILED++))
fi

# Check cache hit rate
cache_hit=$(curl -s http://localhost:8080/metrics | \
    grep "^powerblockade_cache_hit_rate " | awk '{print $2}')

if (( $(echo "$cache_hit >= 50" | bc -l) )); then
    echo "  PASS: Cache hit rate: ${cache_hit}%"
    ((GATES_PASSED++))
elif (( $(echo "$cache_hit < 20" | bc -l) )); then
    echo "  BLOCK: Cache hit rate ${cache_hit}% < 20%"
    ((GATES_FAILED++))
else
    echo "  WARN: Cache hit rate ${cache_hit}% < 50%"
    ((GATES_WARNED++))
fi

# ============================================
# SUMMARY
# ============================================
echo ""
echo "=== Gate Summary ==="
echo "  Passed:  $GATES_PASSED"
echo "  Warned:  $GATES_WARNED"
echo "  Failed:  $GATES_FAILED"
echo ""

if [[ $GATES_FAILED -gt 0 ]]; then
    echo "BLOCK: PROMOTION BLOCKED"
    echo "   Fix failed gates before proceeding."
    exit 1
elif [[ $GATES_WARNED -gt 0 ]]; then
    echo "WARN: PROMOTION ALLOWED WITH WARNINGS"
    echo "   Document warnings in release notes."
    exit 2
else
    echo "PASS: ALL GATES PASSED"
    echo "   Promotion approved."
    exit 0
fi
```

---

## Quick Reference Card

```
+---------------------------------------------------------------------+
|                    REGRESSION GATES QUICK REFERENCE                 |
+---------------------------------------------------------------------+
|                                                                     |
|  OBSERVABILITY (BLOCK on ANY failure)                              |
|  +-- External completeness: >= 99.9%                                |
|  +-- Internal in display: 0                                        |
|                                                                     |
|  PARITY (BLOCK on > 10% delta)                                     |
|  +-- Event count: +/-5% (warn), +/-10% (block)                        |
|  +-- Metrics: +/-5% (warn), +/-10% (block)                            |
|                                                                     |
|  PERFORMANCE                                                        |
|  +-- Cold p50: < 20ms (block if > 25ms)                           |
|  +-- Cold p95: < 100ms (block if > 125ms)                         |
|  +-- Warm p50: < 5ms (block if > 6.25ms)                          |
|  +-- Warm p95: < 20ms (block if > 25ms)                           |
|  +-- Cache hit: > 90% (warn < 80%, block < 50%)                   |
|  +-- Warm QPS: > 4000 (block if < 3200)                           |
|  +-- Latency dist: >= 70% under 50ms (block if < 50%)              |
|                                                                     |
|  WARNING: QPS GAINS DO NOT JUSTIFY PROMOTION IF ANY GATE FAILS          |
|                                                                     |
+---------------------------------------------------------------------+
```

---

# Rollout Runbook: Single-Node Lab Cache Tuning

This runbook provides step-by-step procedures for staged DNS cache tuning in a single-node lab environment. It includes explicit decision points, rollback triggers, and "do not proceed" conditions.

**SCOPE**: Single-node lab deployments only. Production rollout requires a separate runbook with additional safeguards.

---

## Overview

### Purpose

Provide deterministic procedures for:
- Safe, incremental cache tuning
- Baseline capture before changes
- One-knob-at-a-time modifications
- Automated regression gate evaluation
- Immediate rollback on failure
- Complete evidence archival for audit

### Key Principles

```
+---------------------------------------------------------------------+
|                    ROLLOUT PHILOSOPHY                                |
+---------------------------------------------------------------------+
|                                                                     |
|  1. ONE KNOB AT A TIME                                              |
|     Never tune dnsdist AND recursor in the same session.           |
|     Each change must be validated independently.                    |
|                                                                     |
|  2. GATES ARE MANDATORY                                              |
|     All gates must pass before proceeding.                          |
|     No performance gain justifies a gate failure.                   |
|                                                                     |
|  3. ROLLBACK IS ALWAYS READY                                         |
|     Rollback commands documented before starting.                   |
|     Revert at first sign of trouble.                                |
|                                                                     |
|  4. EVIDENCE IS FOREVER                                              |
|     Every run produces an evidence artifact.                        |
|     Failed runs are preserved, not deleted.                         |
|                                                                     |
+---------------------------------------------------------------------+
```

### Tuning Sequence

Per `dns-caching-strategy.md`:

1. **Phase 1**: dnsdist packet cache only
2. **Phase 2**: Recursor cache only (after dnsdist validated)
3. **Phase 3**: Precache scheduler knobs only (after both layers validated)

---

## Pre-Flight Checklist

Complete ALL items before any tuning change.

### System State Verification

```bash
#!/bin/bash
# Preflight checks - exit on any failure

echo "=== Pre-Flight Checklist ==="
echo "Time: $(date -Iseconds)"
echo ""

# 1. All containers healthy
check_container_health() {
    local container=$1
    status=$(docker inspect --format='{{.State.Health.Status}}' $container 2>/dev/null)
    if [[ "$status" != "healthy" ]]; then
        echo "FAIL: $container is $status (expected: healthy)"
        return 1
    fi
    echo "OK: $container is healthy"
    return 0
}

check_container_health "dnsdist" || exit 1
check_container_health "recursor" || exit 1
check_container_health "admin-ui" || exit 1
check_container_health "dnstap-processor" || exit 1

echo ""

# 2. No Prometheus alerts firing
alerts=$(curl -s http://localhost:9090/api/v1/alerts 2>/dev/null | jq -r '.data.alerts | length')
if [[ "$alerts" -gt 0 ]]; then
    echo "FAIL: $alerts Prometheus alerts are firing"
    curl -s http://localhost:9090/api/v1/alerts | jq -r '.data.alerts[] | "  - \(.labels.alertname): \(.state)"'
    exit 1
fi
echo "OK: No Prometheus alerts firing"

# 3. Sufficient disk space (at least 10GB free)
df_output=$(df -BG /var/lib/docker 2>/dev/null || df -BG /)
avail_gb=$(echo "$df_output" | tail -1 | awk '{print $4}' | tr -d 'G')
if [[ "$avail_gb" -lt 10 ]]; then
    echo "FAIL: Only ${avail_gb}GB free disk space (need 10GB+)"
    exit 1
fi
echo "OK: ${avail_gb}GB free disk space"

# 4. Recent successful E2E test
if [[ -f ".sisyphus/evidence/last-e2e-run.txt" ]]; then
    last_run=$(cat .sisyphus/evidence/last-e2e-run.txt)
    run_age=$(( $(date +%s) - $(date -d "$last_run" +%s 2>/dev/null || echo 0) ))
    if [[ $run_age -gt 86400 ]]; then
        echo "WARN: Last E2E test is $(( run_age / 3600 )) hours old"
    else
        echo "OK: Recent E2E test ($(( run_age / 3600 )) hours ago)"
    fi
else
    echo "WARN: No E2E test evidence found"
fi

echo ""
echo "=== Pre-Flight Complete ==="
```

### Configuration Backup

```bash
# Create backup of current config files
BACKUP_DIR="backups/config-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

cp dnsdist/dnsdist.conf.template "$BACKUP_DIR/"
cp recursor/recursor.conf.template "$BACKUP_DIR/"
cp compose.yaml "$BACKUP_DIR/"

# Save current settings from database
psql -c "SELECT key, value FROM settings ORDER BY key" > "$BACKUP_DIR/settings.txt"

# Record git state
git rev-parse HEAD > "$BACKUP_DIR/git-commit.txt"
git status --porcelain > "$BACKUP_DIR/git-status.txt"

echo "Config backup saved to: $BACKUP_DIR"
```

### Rollback Commands Ready

Document exact rollback commands BEFORE making any changes:

```bash
# Create rollback script for this session
ROLLBACK_SCRIPT=".sisyphus/rollback-$(date +%Y%m%d-%H%M%S).sh"

cat > "$ROLLBACK_SCRIPT" << 'ROLLBACK_EOF'
#!/bin/bash
# Rollback script - generated automatically
# Run this script to revert all changes from this tuning session

set -e

echo "=== ROLLBACK INITIATED ==="
echo "Time: $(date -Iseconds)"

# Restore config files from backup
BACKUP_DIR="backups/config-XXXXXXXX-XXXXXX"  # UPDATED BY PREFLIGHT
cp "$BACKUP_DIR/dnsdist.conf.template" dnsdist/
cp "$BACKUP_DIR/recursor.conf.template" recursor/

# Restart affected services
docker compose restart dnsdist recursor

# Wait for health checks
echo "Waiting for services to become healthy..."
sleep 30

# Verify rollback
docker compose ps
echo ""
echo "=== ROLLBACK COMPLETE ==="
echo "Verify system health before proceeding."
ROLLBACK_EOF

# Inject actual backup directory
sed -i "s/backups\/config-XXXXXXXX-XXXXXX/$BACKUP_DIR/" "$ROLLBACK_SCRIPT"
chmod +x "$ROLLBACK_SCRIPT"

echo "Rollback script ready: $ROLLBACK_SCRIPT"
echo "To rollback: $ROLLBACK_SCRIPT"
```

### Pre-Flight Checklist Summary

| Item | Check Command | Pass Criteria |
|------|---------------|---------------|
| All containers healthy | `docker compose ps` | All show "healthy" |
| No Prometheus alerts | `curl localhost:9090/api/v1/alerts` | `alerts: []` |
| Disk space available | `df -h /` | > 10GB free |
| Config backed up | `ls backups/config-*` | Directory exists |
| Rollback script ready | `ls .sisyphus/rollback-*` | Script exists + executable |
| Benchmark tools available | `which dnsperf rec_control` | Both found |

---

## Baseline Capture Procedure

Capture baseline metrics BEFORE any tuning change.

### 1. Record Baseline Metrics

```bash
# Create evidence directory
EVIDENCE_DIR=".sisyphus/evidence/baseline-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$EVIDENCE_DIR"

# Record timestamp
date -Iseconds > "$EVIDENCE_DIR/timestamp.txt"

# Capture Prometheus metrics snapshot
curl -s http://localhost:8080/metrics > "$EVIDENCE_DIR/prometheus-metrics.txt"

# Capture recursor statistics
curl -s "http://recursor:8082/api/v1/servers/localhost/statistics" \
    -H "X-API-Key: ${RECURSOR_API_KEY}" \
    > "$EVIDENCE_DIR/recursor-stats.json"

# Capture dnsdist cache stats
docker compose exec dnsdist dnsdist -e "getPool(''):getCache():printStats()" \
    > "$EVIDENCE_DIR/dnsdist-cache-stats.txt" 2>&1

# Capture database event count (for parity checks)
psql -t -c "SELECT COUNT(*) FROM dns_query_events WHERE ts > now() - interval '1 hour'" \
    | tr -d ' ' > "$EVIDENCE_DIR/event-count-1h.txt"

# Capture cache hit rate baseline
cache_hits=$(psql -t -c "SELECT COUNT(*) FROM dns_query_events WHERE ts > now() - interval '1 hour' AND latency_ms < 5 AND blocked = false" | tr -d ' ')
total_queries=$(psql -t -c "SELECT COUNT(*) FROM dns_query_events WHERE ts > now() - interval '1 hour' AND blocked = false" | tr -d ' ')
if [[ "$total_queries" -gt 0 ]]; then
    cache_hit_rate=$(echo "scale=2; $cache_hits * 100 / $total_queries" | bc)
    echo "$cache_hit_rate" > "$EVIDENCE_DIR/cache-hit-rate.txt"
fi

echo "Baseline captured in: $EVIDENCE_DIR"
```

### 2. Run Baseline Benchmark

```bash
# Run full benchmark suite for baseline
./scripts/benchmarks/dns53-benchmark.sh \
    --mode all \
    --output json \
    --results-dir "$EVIDENCE_DIR/benchmark"

# Verify baseline results
if [[ $? -ne 0 ]]; then
    echo "FAIL: Baseline benchmark failed - fix issues before proceeding"
    exit 1
fi

# Store baseline for comparison
cp "$EVIDENCE_DIR/benchmark/results.json" "$EVIDENCE_DIR/baseline-results.json"

echo "Baseline benchmark complete. Results in: $EVIDENCE_DIR/baseline-results.json"
```

### 3. Baseline Metrics Checklist

| Metric | Source | Recorded |
|--------|--------|----------|
| p50 latency (cold) | benchmark | [ ] |
| p95 latency (cold) | benchmark | [ ] |
| p50 latency (warm) | benchmark | [ ] |
| p95 latency (warm) | benchmark | [ ] |
| QPS (warm) | benchmark | [ ] |
| Cache hit rate | DB query | [ ] |
| Event count (1h) | DB query | [ ] |
| Recursor stats | API | [ ] |
| dnsdist cache stats | CLI | [ ] |

---

## One-Knob Change Procedure

Change exactly ONE setting per tuning session.

### Layer Selection

| Phase | Layer | Config File | Service |
|-------|-------|-------------|---------|
| 1 | dnsdist packet cache | `dnsdist/dnsdist.conf.template` | dnsdist |
| 2 | recursor cache | `recursor/recursor.conf.template` | recursor |
| 3 | precache scheduler | Admin UI Settings | N/A (in-process) |

### dnsdist Packet Cache Changes

**Target settings** (from `dns-caching-strategy.md`):

| Setting | Current | Safe Range | Impact |
|---------|---------|------------|--------|
| `maxEntries` | 500000 | 100000-1000000 | Memory, hit rate |
| `maxTTL` | 86400 | 3600-172800 | Stale data risk |
| `staleTTL` | 60 | 0-300 | Outage resilience |

**Change procedure**:

```bash
# 1. Identify the exact setting to change
SETTING_NAME="maxEntries"  # Example
OLD_VALUE="500000"        # From dns-caching-strategy.md
NEW_VALUE="750000"        # New value (within safe range)

# 2. Edit the config file
vim dnsdist/dnsdist.conf.template

# 3. Validate syntax BEFORE applying
docker compose exec dnsdist dnsdist --check-config -C /etc/dnsdist/dnsdist.conf
if [[ $? -ne 0 ]]; then
    echo "FAIL: Config syntax invalid - aborting"
    git checkout -- dnsdist/dnsdist.conf.template
    exit 1
fi

# 4. Record the change
echo "Change: dnsdist $SETTING_NAME $OLD_VALUE -> $NEW_VALUE" >> "$EVIDENCE_DIR/changes.log"

# 5. Apply by restarting service
docker compose restart dnsdist

# 6. Wait for healthy status
for i in {1..30}; do
    status=$(docker inspect --format='{{.State.Health.Status}}' dnsdist 2>/dev/null)
    if [[ "$status" == "healthy" ]]; then
        echo "dnsdist is healthy after $i seconds"
        break
    fi
    sleep 1
done

# 7. Verify service is responding
dig @127.0.0.1 google.com +short > /dev/null
if [[ $? -ne 0 ]]; then
    echo "FAIL: dnsdist not responding after restart - ROLLBACK NOW"
    $ROLLBACK_SCRIPT
    exit 1
fi
```

### Recursor Cache Changes

**Target settings** (from `dns-caching-strategy.md`):

| Setting | Current | Safe Range | Impact |
|---------|---------|------------|--------|
| `max-cache-entries` | 2000000 | 500000-5000000 | Memory |
| `max-packetcache-entries` | 1000000 | 100000-2000000 | Memory |
| `packetcache-ttl` | 86400 | 3600-172800 | Stale data risk |
| `packetcache-negative-ttl` | 60 | 0-300 | Unblock propagation |

**Change procedure**:

```bash
# 1. Identify the exact setting to change
SETTING_NAME="max-cache-entries"  # Example
OLD_VALUE="2000000"
NEW_VALUE="3000000"

# 2. Edit the config file
vim recursor/recursor.conf.template

# 3. Recursor validates on startup; check logs after restart

# 4. Record the change
echo "Change: recursor $SETTING_NAME $OLD_VALUE -> $NEW_VALUE" >> "$EVIDENCE_DIR/changes.log"

# 5. Apply by restarting service
docker compose restart recursor

# 6. Wait for healthy status
for i in {1..30}; do
    status=$(docker inspect --format='{{.State.Health.Status}}' recursor 2>/dev/null)
    if [[ "$status" == "healthy" ]]; then
        echo "recursor is healthy after $i seconds"
        break
    fi
    sleep 1
done

# 7. Verify recursor is responding
docker compose exec recursor rec_control get cache-hits > /dev/null
if [[ $? -ne 0 ]]; then
    echo "FAIL: recursor not responding after restart - ROLLBACK NOW"
    $ROLLBACK_SCRIPT
    exit 1
fi
```

### Precache Scheduler Changes

**Target settings** (from `dns-caching-strategy.md`):

| Setting | Current | Safe Range | Impact |
|---------|---------|------------|--------|
| `precache_domain_count` | 5000 | 100-10000 | CPU, upstream load |
| `precache_refresh_minutes` | 30 | 5-1440 | Freshness vs load |
| `precache_ignore_ttl` | false | true/false | TTL respect |

**Change procedure**:

```bash
# Precache settings are in the database, changed via Admin UI
# 1. Navigate to Settings page in Admin UI
# 2. Modify the target setting
# 3. Click Save

# Alternative: Direct database update
psql -c "UPDATE settings SET value = '7500' WHERE key = 'precache_domain_count'"

# Record the change
echo "Change: precache_domain_count 5000 -> 7500" >> "$EVIDENCE_DIR/changes.log"

# Changes take effect on next scheduler run (max 30 minutes)
# OR trigger manually:
curl -X POST http://localhost:8080/jobs/trigger-precache
```

---

## Benchmark Run Procedure

After applying the one-knob change, run the benchmark suite.

### Run Post-Change Benchmark

```bash
# Allow cache to stabilize (at least 5 minutes after restart)
echo "Waiting 5 minutes for cache stabilization..."
sleep 300

# Run full benchmark suite
./scripts/benchmarks/dns53-benchmark.sh \
    --mode all \
    --output json \
    --results-dir "$EVIDENCE_DIR/benchmark-after"

benchmark_exit=$?

# Store results
cp "$EVIDENCE_DIR/benchmark-after/results.json" "$EVIDENCE_DIR/after-results.json"

echo "Benchmark complete. Exit code: $benchmark_exit"
```

### Capture Post-Change Metrics

```bash
# Capture post-change metrics for comparison
curl -s http://localhost:8080/metrics > "$EVIDENCE_DIR/prometheus-metrics-after.txt"

curl -s "http://recursor:8082/api/v1/servers/localhost/statistics" \
    -H "X-API-Key: ${RECURSOR_API_KEY}" \
    > "$EVIDENCE_DIR/recursor-stats-after.json"

docker compose exec dnsdist dnsdist -e "getPool(''):getCache():printStats()" \
    > "$EVIDENCE_DIR/dnsdist-cache-stats-after.txt" 2>&1

psql -t -c "SELECT COUNT(*) FROM dns_query_events WHERE ts > now() - interval '1 hour'" \
    | tr -d ' ' > "$EVIDENCE_DIR/event-count-1h-after.txt"
```

---

## Gate Evaluation Procedure

Evaluate all gates. ANY failure requires decision.

### Run Regression Gate Script

```bash
# Run the full regression gate suite
./scripts/regression-gate-check.sh

gate_exit=$?

case $gate_exit in
    0)
        echo "ALL GATES PASSED - proceed to decision"
        ;;
    1)
        echo "GATES FAILED - ROLLBACK or INVESTIGATE"
        ;;
    2)
        echo "GATES PASSED WITH WARNINGS - document and proceed with caution"
        ;;
    *)
        echo "UNKNOWN EXIT CODE - investigate before proceeding"
        ;;
esac
```

### Manual Gate Verification

If the script is unavailable, manually verify each gate:

#### Observability Gates (BLOCK on any failure)

```bash
# External query completeness
curl -s "http://localhost:8080/metrics" | grep powerblockade_queries_total

# Check for internal IPs in recent events
internal_count=$(psql -t -c "SELECT COUNT(*) FROM dns_query_events WHERE ts > now() - interval '1 hour' AND client_ip <<= '172.30.0.0/24' AND is_internal = false" | tr -d ' ')
if [[ "$internal_count" -gt 0 ]]; then
    echo "BLOCK: $internal_count internal queries misflagged"
fi
```

#### Performance Gates

```bash
# Check latency from benchmark results
p50_warm=$(jq '.phases.warm_cache.metrics.p50_latency_ms' "$EVIDENCE_DIR/after-results.json")
p95_warm=$(jq '.phases.warm_cache.metrics.p95_latency_ms' "$EVIDENCE_DIR/after-results.json")

if (( $(echo "$p50_warm > 6.25" | bc -l) )); then
    echo "BLOCK: Warm p50 ($p50_warm ms) exceeds threshold (6.25 ms)"
fi

if (( $(echo "$p95_warm > 25" | bc -l) )); then
    echo "BLOCK: Warm p95 ($p95_warm ms) exceeds threshold (25 ms)"
fi

# Check cache hit rate
cache_hit_rate=$(cat "$EVIDENCE_DIR/cache-hit-rate.txt" 2>/dev/null || echo "unknown")
if [[ "$cache_hit_rate" != "unknown" ]] && (( $(echo "$cache_hit_rate < 50" | bc -l) )); then
    echo "BLOCK: Cache hit rate ($cache_hit_rate%) below critical threshold (50%)"
fi
```

#### Parity Gates

```bash
# Event count parity
baseline_count=$(cat "$EVIDENCE_DIR/event-count-1h.txt")
after_count=$(cat "$EVIDENCE_DIR/event-count-1h-after.txt")

if [[ -n "$baseline_count" && -n "$after_count" && "$baseline_count" -gt 0 ]]; then
    parity_ratio=$(echo "scale=4; $after_count / $baseline_count" | bc)
    if (( $(echo "$parity_ratio < 0.90 || $parity_ratio > 1.10" | bc -l) )); then
        echo "BLOCK: Event parity ratio ($parity_ratio) outside 0.90-1.10 range"
    fi
fi
```

---

## Decision Point: GO / HOLD / ROLLBACK

After gate evaluation, make an explicit decision.

### Decision Matrix

```
+---------------------------------------------------------------------+
|                    DECISION MATRIX                                   |
+---------------------------------------------------------------------+
|                                                                     |
|  GATE RESULTS              DECISION        ACTION                   |
|  -----------------         -----------      -------------------      |
|  All PASS                  GO              Commit, archive, next    |
|  PASS with WARNINGS        GO (caution)    Document, commit, next   |
|  Any BLOCK gate FAIL       ROLLBACK        Revert, investigate      |
|  Performance regression    ROLLBACK        Revert, tune differently |
|  New errors in logs        HOLD            Investigate first        |
|  Observability mismatch    ROLLBACK        Revert immediately       |
|                                                                     |
+---------------------------------------------------------------------+
```

### GO Decision

Proceed to commit and archive.

```bash
echo "DECISION: GO"
echo "Timestamp: $(date -Iseconds)" >> "$EVIDENCE_DIR/decision.log"
echo "Decision: GO - all gates passed" >> "$EVIDENCE_DIR/decision.log"

# Commit the config change
git add dnsdist/dnsdist.conf.template recursor/recursor.conf.template
git commit -m "perf(cache): tune $SETTING_NAME from $OLD_VALUE to $NEW_VALUE

- Baseline: $(cat $EVIDENCE_DIR/baseline-results.json | jq -c '.summary')
- After: $(cat $EVIDENCE_DIR/after-results.json | jq -c '.summary')
- All regression gates passed
- Evidence: $EVIDENCE_DIR"

echo "Change committed. Proceeding to evidence archival."
```

### HOLD Decision

Pause for investigation. Do NOT commit.

```bash
echo "DECISION: HOLD"
echo "Timestamp: $(date -Iseconds)" >> "$EVIDENCE_DIR/decision.log"
echo "Decision: HOLD - investigation required" >> "$EVIDENCE_DIR/decision.log"

# Document the hold reason
read -p "Enter reason for HOLD: " hold_reason
echo "Reason: $hold_reason" >> "$EVIDENCE_DIR/decision.log"

echo ""
echo "HOLD actions:"
echo "1. Investigate the issue"
echo "2. Either fix and re-run benchmark, or ROLLBACK"
echo "3. Do NOT commit until resolved"
echo ""
echo "Current state is preserved. Config not committed."
```

### ROLLBACK Decision

Execute rollback immediately.

```bash
echo "DECISION: ROLLBACK"
echo "Timestamp: $(date -Iseconds)" >> "$EVIDENCE_DIR/decision.log"
echo "Decision: ROLLBACK - gate failure detected" >> "$EVIDENCE_DIR/decision.log"

# Document rollback reason
read -p "Enter reason for ROLLBACK: " rollback_reason
echo "Reason: $rollback_reason" >> "$EVIDENCE_DIR/decision.log"

# Execute rollback
$ROLLBACK_SCRIPT

# Verify rollback success
docker compose ps

echo ""
echo "ROLLBACK complete. System restored to baseline."
echo "Evidence preserved in: $EVIDENCE_DIR"
```

---

## Rollback Procedure

### When to Rollback

Rollback IMMEDIATELY if ANY of these occur:

| Condition | Detection | Action |
|-----------|-----------|--------|
| Observability gate failure | `regression-gate-check.sh` exit 1 | ROLLBACK |
| Latency > 25% regression | Benchmark comparison | ROLLBACK |
| Cache hit rate < 50% | Prometheus metrics | ROLLBACK |
| New errors in logs | `docker compose logs` | ROLLBACK |
| Service unhealthy after change | `docker compose ps` | ROLLBACK |
| SERVFAIL rate > 5% | Prometheus alerts | ROLLBACK |
| Event parity < 90% | DB comparison | ROLLBACK |

### Rollback Commands

#### dnsdist Rollback

```bash
# Restore config
git checkout -- dnsdist/dnsdist.conf.template

# Restart service
docker compose restart dnsdist

# Wait for healthy
for i in {1..30}; do
    [[ $(docker inspect --format='{{.State.Health.Status}}' dnsdist) == "healthy" ]] && break
    sleep 1
done

# Verify
dig @127.0.0.1 google.com +short
```

#### recursor Rollback

```bash
# Restore config
git checkout -- recursor/recursor.conf.template

# Restart service
docker compose restart recursor

# Wait for healthy
for i in {1..30}; do
    [[ $(docker inspect --format='{{.State.Health.Status}}' recursor) == "healthy" ]] && break
    sleep 1
done

# Verify
docker compose exec recursor rec_control get cache-hits
```

#### Cache Flush (if stale data suspected)

```bash
# Flush dnsdist cache
docker compose exec dnsdist dnsdist -e "getPool(''):getCache():expunge(0)"

# Flush recursor cache
docker compose exec recursor rec_control wipe-cache '$'

# Or via API (from blocking.py:174)
curl -X POST http://localhost:8080/blocking/clear-cache
```

### Rollback Verification

```bash
# After rollback, verify system is healthy
echo "=== Rollback Verification ==="

# 1. All containers healthy
docker compose ps

# 2. Quick DNS test
dig @127.0.0.1 google.com +short

# 3. Check for alerts
curl -s http://localhost:9090/api/v1/alerts | jq '.data.alerts | length'

# 4. Run quick benchmark
./scripts/benchmarks/dns53-benchmark.sh --mode warm --duration 30

# 5. Compare with baseline
# Results should be within 5% of baseline
```

---

## Evidence Archival Requirements

All tuning sessions must produce an evidence artifact.

### Evidence Directory Structure

```
.sisyphus/evidence/cache-tuning-YYYYMMDD-HHMMSS/
+-- timestamp.txt              # ISO 8601 timestamp
+-- git-commit.txt              # Git SHA before changes
+-- changes.log                 # What was changed
+-- decision.log                # GO/HOLD/ROLLBACK decision
+-- backup-dir.txt              # Path to config backup
+-- rollback-script.txt         # Path to rollback script
+-- baseline-results.json       # Benchmark before change
+-- after-results.json          # Benchmark after change
+-- prometheus-metrics.txt      # Metrics snapshot (before)
+-- prometheus-metrics-after.txt # Metrics snapshot (after)
+-- recursor-stats.json         # Recursor API stats (before)
+-- recursor-stats-after.json   # Recursor API stats (after)
+-- dnsdist-cache-stats.txt     # dnsdist cache stats (before)
+-- dnsdist-cache-stats-after.txt # dnsdist cache stats (after)
+-- event-count-1h.txt          # DB event count (before)
+-- event-count-1h-after.txt    # DB event count (after)
+-- cache-hit-rate.txt          # Cache hit rate (before)
+-- gate-results.txt            # Regression gate output
+-- benchmark/                  # Full benchmark output
    +-- cold-cache.json
    +-- warm-cache.json
    +-- saturation.json
    +-- results.json
```

### Archive Creation

```bash
# Create evidence archive
ARCHIVE_NAME="cache-tuning-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czvf "$ARCHIVE_NAME" -C .sisyphus/evidence "$(basename $EVIDENCE_DIR)"

# Move to long-term storage
mv "$ARCHIVE_NAME" .sisyphus/archives/

# Retain for at least 90 days
find .sisyphus/archives -name "cache-tuning-*.tar.gz" -mtime +90 -delete
```

### Evidence Retention Policy

| Result | Retention | Location |
|--------|-----------|----------|
| GO (success) | 90 days | `.sisyphus/archives/` |
| ROLLBACK (failure) | 180 days | `.sisyphus/archives/` |
| HOLD (abandoned) | 30 days | `.sisyphus/evidence/` |

---

## Do Not Proceed Conditions

### Mandatory STOP Conditions

**DO NOT PROCEED** if ANY of these are true:

1. **Pre-flight failures**
   - Any container unhealthy
   - Prometheus alerts already firing
   - Less than 10GB free disk space
   - No recent successful E2E test

2. **Baseline failures**
   - Baseline benchmark fails
   - Baseline metrics show existing regression
   - Cannot capture baseline metrics

3. **Change validation failures**
   - Config syntax error
   - Service fails to start after change
   - Service unhealthy after 30 seconds

4. **Post-change failures**
   - Observability gate failure (external completeness < 99.9%)
   - Internal traffic appearing in display
   - Event count parity outside 90-110%
   - New error types in logs

5. **Performance regressions**
   - Latency increase > 25% on any percentile
   - QPS decrease > 20%
   - Cache hit rate drops below 50%
   - SERVFAIL rate > 5%
   - Timeout rate > 2%

6. **Observability mismatches**
   - Metrics endpoint unreachable
   - Recursor API unreachable
   - Log ingestion stopped
   - Grafana dashboards not updating

### Stop Procedure

```bash
# If any STOP condition is detected:
echo "=== STOP CONDITION DETECTED ==="
echo "Time: $(date -Iseconds)"
echo ""

# Document the stop reason
echo "STOP REASON: [describe condition]" >> "$EVIDENCE_DIR/decision.log"

# If change was already applied, ROLLBACK
if [[ -f "$EVIDENCE_DIR/changes.log" ]]; then
    echo "Change was applied. Executing rollback..."
    $ROLLBACK_SCRIPT
else
    echo "No change applied yet. Safe to stop."
fi

# Archive evidence
tar -czvf ".sisyphus/archives/STOPPED-$(date +%Y%m%d-%H%M%S).tar.gz" -C .sisyphus/evidence "$(basename $EVIDENCE_DIR)"

echo "Evidence archived. Do not proceed until condition is resolved."
exit 1
```

---

## Quick Reference Card

```
+---------------------------------------------------------------------+
|                    SINGLE-NODE ROLLOUT QUICK REF                    |
+---------------------------------------------------------------------+
|                                                                     |
|  SEQUENCE:                                                          |
|  1. Pre-flight checklist (all must pass)                           |
|  2. Config backup + rollback script ready                          |
|  3. Baseline benchmark + metrics capture                           |
|  4. ONE KNOB change only                                           |
|  5. Wait 5 min for cache stabilization                             |
|  6. Post-change benchmark + metrics capture                        |
|  7. Run regression gates                                           |
|  8. Decision: GO / HOLD / ROLLBACK                                 |
|  9. Archive evidence                                               |
|                                                                     |
|  LAYERS (one at a time):                                            |
|  Phase 1: dnsdist packet cache                                     |
|  Phase 2: recursor cache                                           |
|  Phase 3: precache scheduler                                       |
|                                                                     |
|  GATE FAILURES (always block):                                      |
|  +-- External completeness < 99.9%                                   |
|  +-- Internal IPs in display                                         |
|  +-- Event parity outside 90-110%                                    |
|  +-- Latency regression > 25%                                        |
|  +-- Cache hit rate < 50%                                            |
|                                                                     |
|  ROLLBACK COMMANDS:                                                 |
|  dnsdist:  git checkout -- dnsdist/ && docker compose restart dnsdist   |
|  recursor: git checkout -- recursor/ && docker compose restart recursor|
|  flush:    docker compose exec dnsdist dnsdist -e "getPool(''):getCache():expunge(0)" |
|  flush:    docker compose exec recursor rec_control wipe-cache '$'   |
|                                                                     |
|  EVIDENCE: .sisyphus/evidence/cache-tuning-YYYYMMDD-HHMMSS/         |
|                                                                     |
+---------------------------------------------------------------------+
```


---

# Rollback Command Packs

Copy-paste executable rollback sequences for staged rollout. Each pack includes pre-rollback snapshots, rollback commands, and post-rollback validation.

**CRITICAL**: Rollback secondary nodes FIRST before rolling back the primary.

---

## Pre-Rollback Snapshot (All Nodes)

Capture system state BEFORE initiating rollback.

```bash
# Create snapshot directory
SNAPSHOT_DIR=".sisyphus/rollback-snapshots/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$SNAPSHOT_DIR"

# Record current version
cat .powerblockade/state.json 2>/dev/null > "$SNAPSHOT_DIR/state.json" || echo 'No state.json' > "$SNAPSHOT_DIR/state.json"

# Export retention settings (PRIMARY ONLY)
docker compose exec postgres psql -U powerblockade -c "SELECT key, value FROM settings WHERE key LIKE 'retention_%';" > "$SNAPSHOT_DIR/retention-settings.txt" 2>/dev/null || echo 'Not primary or postgres unavailable'

# Record node status (PRIMARY ONLY)
curl -s http://localhost:8080/api/nodes 2>/dev/null | jq '.' > "$SNAPSHOT_DIR/nodes-status.json" || echo 'Not primary or API unavailable'

# Capture service status
docker compose ps > "$SNAPSHOT_DIR/services-status.txt"

# Record Prometheus metrics snapshot
curl -s http://localhost:8080/metrics > "$SNAPSHOT_DIR/prometheus-metrics.txt" 2>/dev/null || echo 'Metrics unavailable'

echo "Snapshot saved to: $SNAPSHOT_DIR"
```

---

## Local Development Rollback

For local/lab environments using docker compose.

### Stop Conditions (DO NOT ROLLBACK if)

- Database backup file is missing or corrupted
- Previous version is unknown (no state.json)
- Services are already down and won't restart

### Rollback Commands

```bash
# Local Rollback Pack
# Execute in project root

set -e

# 1. Capture snapshot
SNAPSHOT_DIR=".sisyphus/rollback-snapshots/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$SNAPSHOT_DIR"
docker compose ps > "$SNAPSHOT_DIR/pre-rollback-services.txt"

# 2. Get previous version from state
PREV_VERSION=$(jq -r '.previous_version // empty' .powerblockade/state.json 2>/dev/null)
if [[ -z "$PREV_VERSION" || "$PREV_VERSION" == "null" ]]; then
    echo "ERROR: No previous version in state.json"
    echo "Check .powerblockade/state.json for rollback info"
    exit 1
fi

# 3. Find latest database backup
DB_BACKUP=$(ls -t backups/pre-upgrade-*.sql 2>/dev/null | head -1)
if [[ -z "$DB_BACKUP" ]]; then
    echo "WARN: No database backup found - using --fast mode"
    FAST_MODE="--fast"
else
    echo "Found database backup: $DB_BACKUP"
    FAST_MODE=""
fi

# 4. Execute rollback via pb script
./scripts/pb rollback $FAST_MODE

# 5. Record post-rollback state
docker compose ps > "$SNAPSHOT_DIR/post-rollback-services.txt"
echo "Rollback to $PREV_VERSION complete" > "$SNAPSHOT_DIR/rollback-log.txt"

echo ""
echo "=== Local Rollback Complete ==="
echo "Previous version: $PREV_VERSION"
echo "Snapshot: $SNAPSHOT_DIR"
```

### Post-Rollback Health Checks

```bash
# Local Health Check Pack

echo "=== Post-Rollback Health Check ==="

# 1. Service status
docker compose ps

# 2. Admin UI health
curl -sf http://localhost:8080/health && echo "Admin UI: OK" || echo "Admin UI: FAILED"

# 3. DNS resolution test
dig @127.0.0.1 google.com +short > /dev/null && echo "DNS: OK" || echo "DNS: FAILED"

# 4. Version check
curl -s http://localhost:8080/api/version | jq '.version'

# 5. Retention settings intact (if applicable)
docker compose exec postgres psql -U powerblockade -c "SELECT key, value FROM settings WHERE key LIKE 'retention_%';" 2>/dev/null || echo 'Not applicable'

# 6. No Prometheus alerts
ALERTS=$(curl -s http://localhost:9090/api/v1/alerts 2>/dev/null | jq '.data.alerts | length')
if [[ "$ALERTS" -gt 0 ]]; then
    echo "WARN: $ALERTS Prometheus alerts firing"
    curl -s http://localhost:9090/api/v1/alerts | jq -r '.data.alerts[] | "  - \(.labels.alertname): \(.state)"'
else
    echo "Prometheus: No alerts"
fi

echo ""
echo "=== Health Check Complete ==="
```

---

## bowlister Rollback (Secondary Node)

For secondary node deployed at `/opt/powerblockade`.

### Pre-Conditions

- SSH access to bowlister
- Previous version recorded in `.powerblockade/state.json`
- Secondary node profile (`--profile secondary`)

### Stop Conditions (DO NOT ROLLBACK if)

- Primary (celsate) is unreachable - secondary cannot resync
- Database backup is required (secondaries typically skip DB restore)
- Services are in crash loop

### Rollback Commands

```bash
# bowlister Rollback Pack
# SSH to bowlister and execute

set -e

# 1. SSH to bowlister
# ssh user@bowlister

# 2. Navigate to deployment directory
cd /opt/powerblockade

# 3. Create snapshot
SNAPSHOT_DIR=".sisyphus/rollback-snapshots/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$SNAPSHOT_DIR"
docker compose ps > "$SNAPSHOT_DIR/pre-rollback-services.txt"

# 4. Get previous version
PREV_VERSION=$(jq -r '.previous_version // empty' .powerblockade/state.json 2>/dev/null)
CURRENT_VERSION=$(jq -r '.current_version // "unknown"' .powerblockade/state.json 2>/dev/null)

if [[ -z "$PREV_VERSION" || "$PREV_VERSION" == "null" ]]; then
    echo "ERROR: No previous version found"
    echo "Attempting manual version restore from .env"
    PREV_VERSION=$(grep '^POWERBLOCKADE_VERSION=' .env 2>/dev/null | cut -d= -f2 || true)
    if [[ -z "$PREV_VERSION" ]]; then
        echo "ERROR: Cannot determine previous version - aborting"
        exit 1
    fi
fi

echo "Current version: $CURRENT_VERSION"
echo "Rolling back to: $PREV_VERSION"

# 5. Stop services
docker compose --profile secondary down

# 6. Pull previous version images
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose pull

# 7. Start with previous version
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose --profile secondary up -d

# 8. Wait for health
echo "Waiting for services..."
sleep 10

# 9. Verify services
docker compose ps

# 10. Update state
echo "Rollback complete. Version: $PREV_VERSION" > "$SNAPSHOT_DIR/rollback-log.txt"

echo ""
echo "=== bowlister Rollback Complete ==="
echo "Version: $PREV_VERSION"
```

### Post-Rollback Health Checks

```bash
# bowlister Health Check Pack

echo "=== bowlister Post-Rollback Health ==="

# 1. Service status
docker compose ps

# 2. DNS resolution (local)
dig @127.0.0.1 google.com +short > /dev/null && echo "DNS (local): OK" || echo "DNS (local): FAILED"

# 3. Sync-agent connectivity to primary
docker compose logs sync-agent --tail 20 2>/dev/null | grep -E '(sync|error|fail)' || echo "Sync-agent: No recent sync messages"

# 4. Test connectivity to primary
PRIMARY_URL=$(grep '^PRIMARY_URL=' .env | cut -d= -f2)
if [[ -n "$PRIMARY_URL" ]]; then
    curl -sf "$PRIMARY_URL/health" > /dev/null && echo "Primary connectivity: OK" || echo "Primary connectivity: FAILED"
fi

# 5. No container restarts
RESTARTS=$(docker compose ps --format '{{.Name}}: {{.Status}}' | grep -c 'Restarting' || echo 0)
if [[ "$RESTARTS" -gt 0 ]]; then
    echo "WARN: $RESTARTS containers restarting"
else
    echo "Containers: Stable"
fi

echo ""
echo "=== Health Check Complete ==="
```

---

## celsate Rollback (Primary Node)

For primary node deployed at `/opt/powerblockade` with full stack (Admin UI, database, Grafana).

### Pre-Conditions

- SSH access to celsate
- Database backup exists in `backups/`
- Previous version recorded in `.powerblockade/state.json`
- Primary node runs all services by default (no profile needed)

### Stop Conditions (DO NOT ROLLBACK if)

- Database backup file is missing or corrupted (check with `head backups/pre-upgrade-*.sql`)
- Secondary nodes are already rolled back to a DIFFERENT version
- Services are in crash loop (investigate first)
- No known-good previous version

### Rollback Commands

```bash
# celsate Rollback Pack
# SSH to celsate and execute

set -e

# 1. SSH to celsate
# ssh user@celsate

# 2. Navigate to deployment directory
cd /opt/powerblockade

# 3. Create snapshot
SNAPSHOT_DIR=".sisyphus/rollback-snapshots/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$SNAPSHOT_DIR"

# Capture pre-rollback state
docker compose ps > "$SNAPSHOT_DIR/pre-rollback-services.txt"
docker compose exec postgres psql -U powerblockade -c "SELECT key, value FROM settings WHERE key LIKE 'retention_%';" > "$SNAPSHOT_DIR/retention-pre.txt" 2>/dev/null
curl -s http://localhost:8080/api/nodes | jq '.' > "$SNAPSHOT_DIR/nodes-pre.txt" 2>/dev/null

# 4. Get versions
PREV_VERSION=$(jq -r '.previous_version // empty' .powerblockade/state.json 2>/dev/null)
CURRENT_VERSION=$(jq -r '.current_version // "unknown"' .powerblockade/state.json 2>/dev/null)

if [[ -z "$PREV_VERSION" || "$PREV_VERSION" == "null" ]]; then
    echo "ERROR: No previous version found in state.json"
    exit 1
fi

# 5. Find database backup
DB_BACKUP=$(jq -r '.last_db_backup // empty' .powerblockade/state.json 2>/dev/null)
if [[ -z "$DB_BACKUP" || "$DB_BACKUP" == "null" || ! -f "$DB_BACKUP" ]]; then
    DB_BACKUP=$(ls -t backups/pre-upgrade-*.sql 2>/dev/null | head -1)
fi

echo "Current version: $CURRENT_VERSION"
echo "Rolling back to: $PREV_VERSION"
echo "Database backup: $DB_BACKUP"

read -p "Proceed with rollback? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Rollback cancelled."
    exit 0
fi

# 6. Stop services
docker compose down

# 7. Restore database (if backup exists)
if [[ -n "$DB_BACKUP" && -f "$DB_BACKUP" ]]; then
    echo "Restoring database from $DB_BACKUP..."
    docker compose up -d postgres
    sleep 5
    
    # Drop and recreate schema
    docker compose exec -T postgres psql -U powerblockade -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" powerblockade 2>/dev/null || true
    
    # Restore from backup
    docker compose exec -T postgres psql -U powerblockade powerblockade < "$DB_BACKUP"
    echo "Database restored."
fi

# 8. Pull previous version images
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose pull

# 9. Start with previous version
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose up -d

# 10. Wait for health
echo "Waiting for services to become healthy..."
for i in {1..60}; do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        echo "Admin UI healthy after $i seconds"
        break
    fi
    sleep 1
done

# 11. Update .env with rolled-back version
sed -i "s/^POWERBLOCKADE_VERSION=.*/POWERBLOCKADE_VERSION=$PREV_VERSION/" .env 2>/dev/null || echo "POWERBLOCKADE_VERSION=$PREV_VERSION" >> .env

# 12. Record completion
echo "Rollback to $PREV_VERSION complete at $(date -Iseconds)" > "$SNAPSHOT_DIR/rollback-log.txt"

echo ""
echo "=== celsate Rollback Complete ==="
echo "Version: $PREV_VERSION"
echo "Snapshot: $SNAPSHOT_DIR"
```

### Post-Rollback Health Checks

```bash
# celsate Health Check Pack

echo "=== celsate Post-Rollback Health ==="

# 1. Service status
docker compose ps

# 2. Admin UI health
curl -sf http://localhost:8080/health && echo "Admin UI: OK" || echo "Admin UI: FAILED"

# 3. DNS resolution
dig @127.0.0.1 google.com +short > /dev/null && echo "DNS: OK" || echo "DNS: FAILED"

# 4. Version check
curl -s http://localhost:8080/api/version | jq '.version'

# 5. Retention settings verification
docker compose exec postgres psql -U powerblockade -c "SELECT key, value FROM settings WHERE key LIKE 'retention_%';"

# 6. Node status - verify secondaries are still connected
curl -s http://localhost:8080/api/nodes | jq '.[] | {name, status, last_seen}'

# 7. Data integrity check
docker compose exec postgres psql -U powerblockade -c "SELECT (SELECT COUNT(*) FROM query_logs) as query_logs, (SELECT COUNT(*) FROM node_metrics) as node_metrics, (SELECT COUNT(*) FROM audit_logs) as audit_logs;"

# 8. Grafana accessibility
curl -sf http://localhost:8080/grafana/ > /dev/null && echo "Grafana: OK" || echo "Grafana: FAILED"

# 9. Prometheus alerts
ALERTS=$(curl -s http://localhost:9090/api/v1/alerts 2>/dev/null | jq '.data.alerts | length')
if [[ "$ALERTS" -gt 0 ]]; then
    echo "WARN: $ALERTS Prometheus alerts firing"
    curl -s http://localhost:9090/api/v1/alerts | jq -r '.data.alerts[] | "  - \(.labels.alertname): \(.state)"'
else
    echo "Prometheus: No alerts"
fi

# 10. Compare retention settings with snapshot
if [[ -f "$SNAPSHOT_DIR/retention-pre.txt" ]]; then
    docker compose exec postgres psql -U powerblockade -c "SELECT key, value FROM settings WHERE key LIKE 'retention_%';" > "$SNAPSHOT_DIR/retention-post.txt"
    if diff -q "$SNAPSHOT_DIR/retention-pre.txt" "$SNAPSHOT_DIR/retention-post.txt" > /dev/null; then
        echo "Retention settings: UNCHANGED (OK)"
    else
        echo "WARN: Retention settings changed during rollback"
        diff "$SNAPSHOT_DIR/retention-pre.txt" "$SNAPSHOT_DIR/retention-post.txt"
    fi
fi

echo ""
echo "=== Health Check Complete ==="
```

---

## Rollback Decision Flow

```
+---------------------------------------------------------------------+
|                    ROLLBACK DECISION FLOW                           |
+---------------------------------------------------------------------+
|                                                                     |
|  TRIGGER: Regression gate failure, service failure, or operator     |
|           decision to revert                                        |
|                                                                     |
|  1. CHECK PRE-CONDITIONS                                            |
|     +- Previous version known? (state.json)                         |
|     +- Database backup exists? (primary only)                       |
|     +- Primary reachable? (secondary only)                          |
|     |                                                               |
|     +- NO to any -> INVESTIGATE FIRST, manual rollback may be needed|
|                                                                     |
|  2. ROLLBACK ORDER                                                  |
|     +- SECONDARIES FIRST (bowlister, then other secondaries)        |
|     |   - Use --fast mode (no DB restore needed)                     |
|     |   - Verify connectivity to primary                             |
|     |                                                               |
|     +- PRIMARY LAST (celsate)                                       |
|     |   - Full DB restore                                            |
|     |   - Verify secondaries reconnect                               |
|                                                                     |
|  3. VERIFY EACH NODE                                                |
|     +- Services running?                                            |
|     +- DNS resolving?                                               |
|     +- Health endpoint responding?                                  |
|     |                                                               |
|     +- NO to any -> Investigate, may need manual intervention       |
|                                                                     |
|  4. VALIDATE PRIMARY                                                |
|     +- Retention settings preserved?                                |
|     +- All secondaries online?                                      |
|     +- Data integrity verified?                                     |
|     |                                                               |
|     +- NO to any -> Investigate before declaring success            |
|                                                                     |
|  5. ARCHIVE EVIDENCE                                                |
|     +- Save rollback logs to .sisyphus/archives/                    |
|     +- Document rollback reason                                     |
|                                                                     |
+---------------------------------------------------------------------+
```

---

## Quick Reference: Rollback Commands

```
+---------------------------------------------------------------------+
|                    ROLLBACK QUICK REFERENCE                         |
+---------------------------------------------------------------------+
|                                                                     |
|  LOCAL (lab/dev):                                                   |
|  +-- ./scripts/pb rollback              # Standard (with DB)         |
|  +-- ./scripts/pb rollback --fast       # Fast (no DB restore)       |
|                                                                     |
|  BOWLISTER (secondary):                                             |
|  +-- cd /opt/powerblockade && \                                    |
|  |   POWERBLOCKADE_VERSION=<prev> docker compose pull && \         |
|  |   POWERBLOCKADE_VERSION=<prev> docker compose --profile secondary up -d
|                                                                     |
|  CELSATE (primary):                                                 |
  |   docker compose down && \                                    
|  |   # (restore DB if needed) && \                                 
|  |   POWERBLOCKADE_VERSION=<prev> docker compose pull && \         
  |   POWERBLOCKADE_VERSION=<prev> docker compose up -d
|                                                                     
|  HEALTH CHECKS:                                                     
|  +-- curl -sf http://localhost:8080/health                         
|  +-- dig @127.0.0.1 google.com +short                              
|  +-- docker compose ps                                              
|                                                                     
|  ROLLBACK ORDER: Secondaries FIRST, then primary                   
|                                                                     
+---------------------------------------------------------------------+
```