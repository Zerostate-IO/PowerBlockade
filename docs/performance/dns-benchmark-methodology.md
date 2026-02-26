# DNS53 Benchmark Methodology

Repeatable benchmark procedures for PowerBlockade DNS performance testing. This methodology ensures consistent, comparable results across runs and environments.

## Overview

| Phase | Purpose | Cache State | Duration |
|-------|---------|-------------|----------|
| Cold Cache | Baseline resolution performance | Empty | 60s |
| Warm Cache | Cached resolution performance | Primed | 60s |
| Saturation | Maximum throughput / stress | Mixed | 120s |

**Tools required**: `dnsperf`, `resperf` (DNS-OARC), `dig`, `rec_control`

## Corpus Construction

### Stable Control Set (Required)

A fixed set of domains used across all benchmark runs for comparison. Store in version control.

**Location**: `docs/performance/corpus/control-domains.txt`

**Construction rules**:
- 50 domains minimum, 200 domains recommended
- Mix of TLDs: .com (40%), .org (15%), .net (10%), ccTLDs (35%)
- Include CDN-backed domains (cloudflare.com, fastly.com)
- Include high-TTL domains (TTL > 3600s preferred for cache stability)
- Exclude domains known to geolocate or anycast inconsistently
- Verify all domains resolve before including

**Format** (dnsperf compatible):
```
google.com A
cloudflare.com A
github.com A
amazon.com A
microsoft.com A
```

### Realistic Traffic Corpus

Generated from actual query patterns. Must persist seed for reproducibility.

**Location**: `docs/performance/corpus/traffic-corpus-{seed}.txt`

**Construction rules**:
1. Extract top N domains from PowerBlockade query logs (see `precache.py:46`)
2. Filter: blocked=false, rcode=0 (successful resolutions only)
3. Deduplicate and normalize (lowercase, strip trailing dot)
4. Shuffle with **persistent seed**
5. Limit to target size (1000-10000 domains typical)

**Seed persistence requirement**:
```bash
# Generate corpus with explicit seed (STORE THIS SEED)
SEED=42
python3 scripts/generate-corpus.py \
  --hours 24 \
  --limit 5000 \
  --seed $SEED \
  --output docs/performance/corpus/traffic-corpus-${SEED}.txt
```

**Metadata file** (required alongside corpus):
```json
// docs/performance/corpus/traffic-corpus-42.meta.json
{
  "seed": 42,
  "generated_at": "2026-02-26T00:00:00Z",
  "source_hours": 24,
  "domain_count": 4823,
  "control_set_version": "v1.0"
}
```

## Benchmark Phases

### Phase 1: Cold Cache

Measures baseline resolution performance with empty cache.

**Pre-conditions**:
- Recursor running for at least 30 seconds
- No prior queries in cache

**Flush procedure**:
```bash
# Flush recursor cache via API
rec_control --socket-dir=/var/run/pdns-recursor \
  --apikey=${RECURSOR_API_KEY} \
  wipe-cache '$'

# Alternative: restart recursor (more thorough)
docker compose restart recursor
sleep 10  # Wait for recursor to be ready
```

**Run command**:
```bash
dnsperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/control-domains.txt \
  -l 60 \
  -Q 1000 \
  -m udp \
  -o json \
  > results/cold-cache-$(date +%Y%m%d-%H%M%S).json
```

**Parameters**:
- `-l 60`: 60 second duration
- `-Q 1000`: Target 1000 queries/second (self-paced)
- `-m udp`: UDP transport only (baseline)

**Metrics collected**:
| Metric | Description |
|--------|-------------|
| `queries_sent` | Total queries issued |
| `queries_completed` | Successful responses |
| `queries_lost` | Timeouts/errors |
| `avg_latency_ms` | Mean response time |
| `p50_latency_ms` | 50th percentile latency |
| `p95_latency_ms` | 95th percentile latency |
| `p99_latency_ms` | 99th percentile latency |
| `qps_actual` | Achieved queries per second |

### Phase 2: Warm Cache

Measures cached resolution performance.

**Warmup procedure**:
```bash
# Prime cache with control set (run 3x to ensure caching)
for i in 1 2 3; do
  dnsperf -s 127.0.0.1 -p 53 \
    -d docs/performance/corpus/control-domains.txt \
    -l 30 \
    -Q 500 \
    -m udp \
    > /dev/null
  sleep 2
done

# Verify cache hit ratio
curl -s http://recursor:8082/api/v1/servers/localhost/statistics \
  | jq '.[] | select(.name == "cache-hits") | .value'
```

**Run command**:
```bash
dnsperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/control-domains.txt \
  -l 60 \
  -Q 5000 \
  -m udp \
  -o json \
  > results/warm-cache-$(date +%Y%m%d-%H%M%S).json
```

**Higher QPS target** reflects expected cache performance.

**Additional metrics**:
| Metric | Source |
|--------|--------|
| `cache_hit_ratio` | recursor API `/statistics` |
| `cache_entries` | recursor API `/statistics` |
| `cache_bytes` | recursor API `/statistics` |

**Fetch cache statistics**:
```bash
curl -s http://recursor:8082/api/v1/servers/localhost/statistics \
  -H "X-API-Key: ${RECURSOR_API_KEY}" \
  | jq '{
      cache_hits: (.[] | select(.name == "cache-hits") | .value),
      cache_misses: (.[] | select(.name == "cache-misses") | .value),
      cache_entries: (.[] | select(.name == "cache-entries") | .value)
    }'
```

### Phase 3: Saturation

Measures maximum throughput and behavior under load.

**Run command (resperf)**:
```bash
resperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/traffic-corpus-42.txt \
  -m 100000 \
  -i 1 \
  -o json \
  > results/saturation-$(date +%Y%m%d-%H%M%S).json
```

**Parameters**:
- `-m 100000`: Maximum QPS target
- `-i 1`: Increment QPS by 1 per second until failure

**What it measures**:
- Maximum sustainable QPS before degradation
- Latency degradation curve under load
- Error rate as load increases

**Alternative: sustained high load with dnsperf**:
```bash
dnsperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/traffic-corpus-42.txt \
  -l 120 \
  -Q 10000 \
  -m udp \
  -o json \
  > results/saturation-sustained-$(date +%Y%m%d-%H%M%S).json
```

## Output Schema

### Benchmark Result JSON

```json
{
  "metadata": {
    "benchmark_id": "bm-20260226-001",
    "run_at": "2026-02-26T14:30:00Z",
    "tool": "dnsperf",
    "tool_version": "2.15.0",
    "target": {
      "host": "127.0.0.1",
      "port": 53,
      "transport": "udp"
    },
    "corpus": {
      "file": "control-domains.txt",
      "domain_count": 200,
      "seed": null
    },
    "phase": "cold-cache",
    "duration_seconds": 60
  },
  "metrics": {
    "queries_sent": 60000,
    "queries_completed": 59820,
    "queries_lost": 180,
    "avg_latency_ms": 12.5,
    "p50_latency_ms": 8.2,
    "p95_latency_ms": 45.1,
    "p99_latency_ms": 89.3,
    "min_latency_ms": 2.1,
    "max_latency_ms": 245.6,
    "qps_target": 1000,
    "qps_actual": 997.0
  },
  "cache_stats": {
    "cache_hits": null,
    "cache_misses": null,
    "cache_hit_ratio": null,
    "note": "not applicable for cold-cache phase"
  },
  "environment": {
    "hostname": "powerblockade-01",
    "recursor_version": "5.2.0",
    "threads": 2,
    "memory_mb": 512
  }
}
```

### Comparison Report Schema

```json
{
  "comparison_id": "cmp-20260226-001",
  "baseline": {
    "run_id": "bm-20260225-001",
    "metadata": { "..." },
    "metrics": { "..." }
  },
  "current": {
    "run_id": "bm-20260226-001",
    "metadata": { "..." },
    "metrics": { "..." }
  },
  "delta": {
    "avg_latency_ms": { "value": -2.1, "percent": -16.8 },
    "p95_latency_ms": { "value": -5.2, "percent": -10.3 },
    "qps_actual": { "value": 50, "percent": 5.3 }
  },
  "regression_detected": false,
  "thresholds": {
    "latency_increase_percent": 20,
    "qps_decrease_percent": 10
  }
}
```

## Full Benchmark Sequence

Run all phases in sequence with proper cache state management:

```bash
#!/bin/bash
# scripts/run-benchmark.sh

set -e
RESULTS_DIR="results/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RESULTS_DIR"

echo "=== PowerBlockade DNS Benchmark ==="
echo "Results: $RESULTS_DIR"

# Pre-flight checks
command -v dnsperf >/dev/null || { echo "ERROR: dnsperf not installed"; exit 1; }
command -v rec_control >/dev/null || { echo "ERROR: rec_control not installed"; exit 1; }

# Record baseline cache stats
echo "Recording baseline..."
curl -s "http://recursor:8082/api/v1/servers/localhost/statistics" \
  -H "X-API-Key: ${RECURSOR_API_KEY}" \
  > "$RESULTS_DIR/baseline-stats.json"

# Phase 1: Cold Cache
echo "Phase 1: Cold Cache"
rec_control wipe-cache '$'
sleep 2
dnsperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/control-domains.txt \
  -l 60 -Q 1000 -m udp -o json \
  > "$RESULTS_DIR/cold-cache.json"

# Phase 2: Warm Cache
echo "Phase 2: Warm Cache (warming up...)"
for i in 1 2 3; do
  dnsperf -s 127.0.0.1 -p 53 \
    -d docs/performance/corpus/control-domains.txt \
    -l 30 -Q 500 -m udp > /dev/null
  sleep 2
done

curl -s "http://recursor:8082/api/v1/servers/localhost/statistics" \
  -H "X-API-Key: ${RECURSOR_API_KEY}" \
  > "$RESULTS_DIR/pre-warm-stats.json"

dnsperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/control-domains.txt \
  -l 60 -Q 5000 -m udp -o json \
  > "$RESULTS_DIR/warm-cache.json"

curl -s "http://recursor:8082/api/v1/servers/localhost/statistics" \
  -H "X-API-Key: ${RECURSOR_API_KEY}" \
  > "$RESULTS_DIR/post-warm-stats.json"

# Phase 3: Saturation (optional, requires larger corpus)
if [[ -f "docs/performance/corpus/traffic-corpus-42.txt" ]]; then
  echo "Phase 3: Saturation"
  resperf -s 127.0.0.1 -p 53 \
    -d docs/performance/corpus/traffic-corpus-42.txt \
    -m 100000 -i 1 -o json \
    > "$RESULTS_DIR/saturation.json"
else
  echo "Skipping Phase 3: traffic corpus not found"
fi

echo "=== Benchmark Complete ==="
echo "Results saved to: $RESULTS_DIR"
```

## Metrics Reference

### Primary Metrics (compare across runs)

| Metric | Target (Cold) | Target (Warm) | Notes |
|--------|---------------|---------------|-------|
| `p50_latency_ms` | < 20ms | < 5ms | Median response time |
| `p95_latency_ms` | < 100ms | < 20ms | Tail latency |
| `p99_latency_ms` | < 200ms | < 50ms | Worst-case latency |
| `qps_actual` | > 500 | > 4000 | Queries per second |
| `queries_lost` | < 1% | < 0.1% | Error rate |

### Cache Metrics (warm phase only)

| Metric | Target | Notes |
|--------|--------|-------|
| `cache_hit_ratio` | > 90% | (hits / (hits + misses)) |
| `cache_entries` | Varies | Domains in cache |

### Saturation Metrics

| Metric | Target | Notes |
|--------|--------|-------|
| `max_qps_sustained` | > 5000 | Before >5% loss |
| `latency_at_50pct_load` | < 2x cold | Degradation factor |
| `error_rate_at_max` | < 5% | At maximum tested QPS |

## Tool Installation

```bash
# Ubuntu/Debian
apt-get install dnsperf

# CentOS/RHEL
yum install dnsperf

# macOS
brew install dnsperf

# From source (DNS-OARC)
git clone https://codeberg.org/DNS-OARC/dnsperf.git
cd dnsperf
./configure
make
make install
```
```

## dns53-benchmark.sh Script Contract

The `scripts/benchmarks/dns53-benchmark.sh` script automates the benchmark process. This section defines its interface contract.

### CLI Interface

```
USAGE:
    dns53-benchmark.sh [OPTIONS]

OPTIONS:
    --mode <mode>           Benchmark mode(s) to run (default: all)
                            Values: cold, warm, saturation, all

    --target <host>         DNS server address (default: 127.0.0.1)

    --port <port>           DNS server port (default: 53)

    --corpus <path>         Path to domain corpus file (default: auto-detect)

    --duration <seconds>    Duration per phase in seconds (default: 60)
                            Saturation phase uses 2x this value

    --output <format>       Output format (default: json)
                            Values: json, markdown, both

    --results-dir <path>    Directory to save results (default: results/)

    --help, -h              Show help message

    --version, -v           Show version information
```

### Exit Codes

| Code | Meaning | Description |
|------|---------|-------------|
| 0 | SUCCESS | All phases passed, no regressions detected |
| 1 | PHASE_FAILED | One or more phases failed (performance regression) |
| 2 | PREREQ_FAILED | Prerequisites not met (missing tools, no network access) |
| 3 | CONFIG_ERROR | Configuration error (invalid arguments, missing files) |

**Usage in CI/CD**:
```bash
# Run benchmark and check exit code
./scripts/benchmarks/dns53-benchmark.sh --mode all --output json
exit_code=$?

if [[ $exit_code -eq 0 ]]; then
    echo "All benchmarks passed"
elif [[ $exit_code -eq 1 ]]; then
    echo "Performance regression detected!"
    # Fail the build
    exit 1
elif [[ $exit_code -eq 2 ]]; then
    echo "Prerequisites not met - check tool installation"
    exit 1
elif [[ $exit_code -eq 3 ]]; then
    echo "Configuration error - check arguments"
    exit 1
fi
```

### JSON Output Schema

The JSON output is designed for machine consumption by regression gates and CI systems.

```json
{
  "benchmark_id": "bm-20260226-001",
  "run_at": "2026-02-26T14:30:00Z",
  "script_version": "1.0.0",
  "config": {
    "target": "127.0.0.1",
    "port": 53,
    "mode": "all",
    "corpus": "control-domains.txt",
    "duration_seconds": 60
  },
  "environment": {
    "hostname": "powerblockade-01",
    "recursor_version": "5.2.0",
    "os": "Linux",
    "kernel": "5.15.0"
  },
  "prerequisites": {
    "dnsperf": { "installed": true, "version": "2.15.0" },
    "rec_control": { "installed": true },
    "jq": { "installed": true },
    "network_access": { "ok": true, "latency_ms": 1.2 }
  },
  "phases": {
    "cold_cache": {
      "implemented": true,
      "passed": true,
      "metrics": {
        "queries_sent": 60000,
        "queries_completed": 59820,
        "queries_lost": 180,
        "avg_latency_ms": 12.5,
        "p50_latency_ms": 8.2,
        "p95_latency_ms": 45.1,
        "p99_latency_ms": 89.3,
        "qps_actual": 997.0
      },
      "thresholds": {
        "p50_limit_ms": 20,
        "p95_limit_ms": 100
      }
    },
    "warm_cache": {
      "implemented": true,
      "passed": true,
      "metrics": {
        "queries_sent": 300000,
        "queries_completed": 299500,
        "queries_lost": 500,
        "avg_latency_ms": 3.2,
        "p50_latency_ms": 2.1,
        "p95_latency_ms": 8.5,
        "p99_latency_ms": 15.2,
        "qps_actual": 4820.0,
        "cache_hit_ratio": 0.95
      },
      "thresholds": {
        "p50_limit_ms": 5,
        "p95_limit_ms": 20,
        "cache_hit_limit_pct": 90
      }
    },
    "saturation": {
      "implemented": true,
      "passed": true,
      "metrics": {
        "max_qps_sustained": 12500,
        "latency_at_50pct_ms": 15.0,
        "error_rate_pct": 2.1
      },
      "thresholds": {
        "min_qps": 5000
      }
    }
  },
  "summary": {
    "passed": true,
    "phases_run": 3,
    "phases_passed": 3,
    "phases_failed": 0,
    "regressions": []
  }
}
```

### Markdown Output Format

The Markdown output provides human-readable summaries for reports.

```markdown
# DNS53 Benchmark Report

**Run ID**: bm-20260226-001  
**Date**: 2026-02-26 14:30:00 UTC  
**Target**: 127.0.0.1:53  
**Mode**: all  

## Summary

| Phase | Status | QPS | p50 | p95 | Notes |
|-------|--------|-----|-----|-----|-------|
| Cold Cache | PASS | 997 | 8ms | 45ms | - |
| Warm Cache | PASS | 4820 | 2ms | 9ms | 95% cache hit |
| Saturation | PASS | 12500 | 15ms | 62ms | Sustained at 12.5k QPS |

## Environment

- **Hostname**: powerblockade-01
- **Recursor**: PowerDNS Recursor 5.2.0
- **OS**: Ubuntu 22.04 (Linux 5.15.0)

## Configuration

- **Corpus**: control-domains.txt
- **Duration**: 60s per phase

## Verdict: ALL PHASES PASSED
```

### Prerequisites

Before running the benchmark script, ensure:

| Requirement | Install Command | Check Command |
|-------------|-----------------|---------------|
| dnsperf | `apt-get install dnsperf` | `dnsperf -V` |
| rec_control | PowerDNS Recursor package | `rec_control --help` |
| jq | `apt-get install jq` | `jq --version` |
| Network access | N/A | `dig @<target> google.com` |

**Environment Variables**:
```bash
# Required for cache operations
export RECURSOR_API_KEY="your-api-key"
export RECURSOR_API_URL="http://recursor:8082"

# Optional: Override defaults
export DNS53_BENCHMARK_TARGET="127.0.0.1"
export DNS53_BENCHMARK_DURATION="60"
```

### Threshold Configuration

Default thresholds can be overridden via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DNS53_COLD_P50_THRESHOLD_MS` | 20 | Cold cache p50 latency limit (ms) |
| `DNS53_COLD_P95_THRESHOLD_MS` | 100 | Cold cache p95 latency limit (ms) |
| `DNS53_WARM_P50_THRESHOLD_MS` | 5 | Warm cache p50 latency limit (ms) |
| `DNS53_WARM_P95_THRESHOLD_MS` | 20 | Warm cache p95 latency limit (ms) |
| `DNS53_WARM_CACHE_HIT_PCT` | 90 | Warm cache hit ratio minimum (%) |
| `DNS53_SATURATION_MIN_QPS` | 5000 | Saturation minimum sustainable QPS |

Example:
```bash
# Stricter thresholds for production CI
export DNS53_COLD_P95_THRESHOLD_MS=50
export DNS53_WARM_CACHE_HIT_PCT=95
./scripts/benchmarks/dns53-benchmark.sh --mode all
```

## Out of Scope

- DoH (DNS over HTTPS) benchmarking
- DoT (DNS over TLS) benchmarking
- Anycast/geographic latency testing
- Authoritative server testing (recursor only)

## Appendix: rec_control Commands

```bash
# Flush entire cache
rec_control wipe-cache '$'

# Flush specific domain
rec_control wipe-cache example.com

# Flush domain and all subdomains
rec_control wipe-cache example.com$

# Get cache statistics
rec_control get cache-hits
rec_control get cache-misses
rec_control get cache-entries

# Get all statistics
rec_control get-all
```
