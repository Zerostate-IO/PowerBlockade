# DNS53 Benchmark Methodology

Repeatable benchmark procedures for PowerBlockade DNS performance testing. This methodology ensures consistent, comparable results across runs and environments.

## Overview

| Phase | Purpose | Cache State | Duration |
|-------|---------|-------------|----------|
| Cold Cache | Baseline resolution performance | Empty (both layers, verified) | 60s |
| Warm Cache | Cached resolution performance | Primed | 60s |
| Saturation | Maximum throughput / stress | Mixed | 120s |
| Time-to-Warm | Cold -> stably-warm transition | Cleared -> warming | 5 x 30s windows (default) |

**Tools required**: `dnsperf >= 2.14.0` (DNS-OARC), `dig`, `docker` (cache
clearing and counters via the compose containers), `jq`, `bc`. dnsperf must
be built with Concurrency Kit histograms (`-O latency-histogram`); the
harness fails loudly when percentiles are unavailable.

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
- BOTH cache layers empty (dnsdist packet cache AND recursor caches) —
  verified from live counters, never assumed

**Contract (fail-closed)**: every clearing step is verified before any
traffic is sent; a failed or unverifiable clear aborts the phase instead of
measuring a warm cache and calling it cold.

**Prerequisite (console clearing)**: the dnsdist console must be enabled.
Set `DNSDIST_CONSOLE_KEY` in `.env` (generate with
`head -c 32 /dev/urandom | base64 -w0`) and recreate the dnsdist container;
its entrypoint appends `setKey(...)` + `controlSocket("127.0.0.1:5199")` to
the generated config. The console is reachable only via `docker exec`
inside the container. Without it the harness fails closed with a fix-it
message (the only alternative is the destructive restart mode below).

**Flush procedure (non-disruptive, default)**:
```bash
# 1. Recursor: wipe record + packet + negative caches
docker compose exec recursor rec_control \
  --socket-dir=/var/run/pdns-recursor wipe-cache '$'

# 2. dnsdist: empty the packet cache of the default pool via the console.
#    clearCache()/mvCacheToDownstream() do NOT exist in dnsdist 2.0.8;
#    expunge(0) keeps 0 entries (verified against the 2.0.8 source).
docker compose exec dnsdist dnsdist -c -C /tmp/dnsdist.conf \
  -e "getPool(''):getCache():expunge(0)"

# 3. Verify the floor from live counters (NOT from tool exit codes - the
#    dnsdist console client exits 0 even on auth failure):
#    dnsdist packet cache entries == 0
#    recursor cache-entries == 0 AND packetcache-entries == 0
```

**Restart clearing (destructive fallback)**: if console clearing is
unavailable, the harness can clear via container restarts when invoked with
the explicit opt-in `--clear-mode restart`. It refuses any other
`--clear-mode` value, restarts ONLY the dnsdist and recursor containers,
waits (bounded, default 180s) for BOTH to report healthy BEFORE any pre-run
counters are taken, and then verifies both cache occupancies are at the
floor. Manual checklist:

| Step | Command / check | Gate |
|------|-----------------|------|
| 1 | Announce maintenance window (client connections drop) | operator |
| 2 | `docker compose restart dnsdist recursor` | rc == 0 |
| 3 | Poll `docker inspect --format='{{.State.Health.Status}}' dnsdist` until `healthy` | fail on timeout |
| 4 | Same for `recursor` | fail on timeout |
| 5 | Verify dnsdist entries == 0, recursor cache-entries == 0, packetcache-entries == 0 | fail closed |

**Run command** (dnsperf has NO JSON output at any version; percentiles come
from the latency histogram added in dnsperf 2.14.0 — the harness requires
`dnsperf >= 2.14.0` and fails loudly on any unknown output format instead
of nulling percentiles):
```bash
dnsperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/control-domains.txt \
  -l 60 \
  -Q 1000 \
  -m udp \
  -O latency-histogram \
  > results/cold-cache-$(date +%Y%m%d-%H%M%S).txt
```

**Parameters**:
- `-l 60`: 60 second duration
- `-Q 1000`: Target 1000 queries/second (self-paced)
- `-m udp`: UDP transport only (baseline)
- `-O latency-histogram`: per-response latency buckets; p50/p95/p99 are
  computed from the buckets (bucket upper bound, converted to ms)

**Metrics collected**:
| Metric | Description |
|--------|-------------|
| `queries_sent` | Total queries issued |
| `queries_completed` | Successful responses |
| `queries_lost` | Timeouts/errors |
| `avg_latency_ms` | Mean response time
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
```

**Run command**:
```bash
dnsperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/control-domains.txt \
  -l 60 \
  -Q 5000 \
  -m udp \
  -O latency-histogram \
  > results/warm-cache-$(date +%Y%m%d-%H%M%S).txt
```

**Higher QPS target** reflects expected cache performance.

**Cache hit ratios are computed from counter DELTAS**, never from absolute
counters: a snapshot is taken immediately before the run and another after;
per-layer ratio = `delta_hits / (delta_hits + delta_misses)`. This excludes
warmup and background traffic from the measurement.

| Layer | Counters | Pass gate (default) |
|-------|----------|---------------------|
| dnsdist packet cache | `hits`/`misses` from `getStats()` (console) or `/jsonstat` `pools[name=""]` | >= 90% (`DNS53_WARM_CACHE_HIT_PCT`) |
| recursor packet cache | `packetcache-hits`/`packetcache-misses` | reported, not gated |
| recursor record cache | `cache-hits`/`cache-misses` | reported, not gated |

**Counter sources** (per layer, tried in order; the harness degrades with a
clear message when a source is unavailable and fails closed if NO source
works for a layer a phase needs):

| Layer | Primary (works from the host on every branch) | Optional HTTP source |
|-------|----------------------------------------------|----------------------|
| dnsdist | console `getPool(''):getCache():getStats()` via `docker exec` (needs `DNSDIST_CONSOLE_KEY`) | `DNSDIST_STATS_URL` + `/jsonstat` with basic auth (`DNSDIST_WEB_PASSWORD`, any username; integration branch, compose-network only) |
| recursor | `docker exec <recursor> rec_control --socket-dir=... get ...` (values-only output, order-preserving) | `RECURSOR_METRICS_URL` + `/metrics` with basic auth (`RECURSOR_WEB_PASSWORD`, any username) |

**Warming quiesce**: the admin-ui precache warming job (fires every 5
minutes) is paused during measurement by flipping
`settings.precache_enabled` to `false` via psql in the postgres container —
the same mechanism as the operations runbook's precache tuning. The job
re-reads the setting each time it fires, so the pause takes effect at the
next fire (bounded skew: a run already in flight when the flag flips can
still finish; recorded in the result JSON as `precache_pause`). The HTTP
alternative (`POST /precache/settings`) was rejected: it requires an
authenticated admin session and rewrites every precache field with form
defaults. The original setting is restored after the run (also on abnormal
exit, via the harness's exit trap).

**Additional metrics**:
| Metric | Source |
|--------|--------|
| `counter_deltas.dnsdist.hit_ratio_pct` | dnsdist console/jsonstat deltas |
| `counter_deltas.recursor_packetcache.hit_ratio_pct` | recursor /metrics or rec_control deltas |
| `counter_deltas.recursor_recordcache.hit_ratio_pct` | recursor /metrics or rec_control deltas |
| `cache_entries` / occupancy | stats snapshot (baseline section) |

### Phase 3: Saturation

Measures maximum throughput and behavior under load.

**Method**: sustained dnsperf load at fixed QPS (default 10000 for 2x the
phase duration). resperf is NOT used: its text output could not be verified
against a known format (the previous harness grepped for markers that do
not exist in resperf's output and silently fell back); the repaired harness
only parses formats it can validate and fails loudly otherwise.

**Run command**:
```bash
dnsperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/traffic-corpus-42.txt \
  -l 120 \
  -Q 10000 \
  -m udp \
  -O latency-histogram \
  > results/saturation-sustained-$(date +%Y%m%d-%H%M%S).txt
```

**What it measures**:
- Sustained throughput at the target rate (fallback: actual achieved QPS)
- Latency degradation under load
- Error/loss rate under load

### Phase 4: Time-to-Warm

Measures how long the stack takes to go from cold to stably-warm under
continuous load.

**Definition**: starting from a verified-cold state (both cache layers
emptied and floor-verified, same procedure as Phase 1), drive continuous
load in windows of `TTW_WINDOW_SECONDS` (default 30s) at `TTW_QPS`
(default 500). A window **passes** when:

- its dnsperf p99 <= `DNS53_TTW_P99_THRESHOLD_MS` (default 50ms), AND
- the dnsdist packet-cache window hit ratio >= `DNS53_TTW_DNSDIST_HIT_PCT`
  (default 90%), AND
- the recursor packet-cache window hit ratio >=
  `DNS53_TTW_PACKETCACHE_HIT_PCT` (default 90%), AND
- the recursor record-cache window hit ratio >=
  `DNS53_TTW_RECCACHE_HIT_PCT` (default 90%)

All ratios are window-local counter DELTAS (snapshot at window boundaries).
The stack counts as **warm** after `TTW_WINDOWS` (default 5) consecutive
passing windows. **Time-to-warm** is the elapsed wall-clock time from the
clear until the end of the final window of that streak. If no streak forms
within `DNS53_TTW_MAX_WINDOWS` (default 40) windows, the phase fails with
per-window diagnostics.

Defaults: 5 windows x 30s = a criterion that must hold for 2.5 minutes of
continuous load — long enough to ride out TTL/refresh transients, short
enough for a practical maintenance-window measurement.

The precache warming job is paused for this phase (same quiesce as Phase 2)
so "warming" measures only the measurement load, not the admin-ui job.

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
command -v jq >/dev/null || { echo "ERROR: jq not installed"; exit 1; }
# dnsperf >= 2.14.0 required (-O latency-histogram; no JSON output exists)

# Record baseline snapshot (occupancy, memory, threads, pipeline health)
# ... dnsdist getStats() + recursor rec_control get + docker stats --no-stream

# Phase 1: Cold Cache (clear BOTH layers, verify floor, then measure)
echo "Phase 1: Cold Cache"
docker compose exec recursor rec_control --socket-dir=/var/run/pdns-recursor wipe-cache '$'
docker compose exec dnsdist dnsdist -c -C /tmp/dnsdist.conf \
  -e "getPool(''):getCache():expunge(0)"
# ... verify: dnsdist entries == 0, recursor cache-entries == 0,
#     packetcache-entries == 0 (abort if not)
dnsperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/control-domains.txt \
  -l 60 -Q 1000 -m udp -O latency-histogram \
  > "$RESULTS_DIR/cold-cache.txt"

# Phase 2: Warm Cache
echo "Phase 2: Warm Cache (warming up...)"
for i in 1 2 3; do
  dnsperf -s 127.0.0.1 -p 53 \
    -d docs/performance/corpus/control-domains.txt \
    -l 30 -Q 500 -m udp > /dev/null
  sleep 2
done

# Snapshot counters BEFORE the measured run (hit ratios use deltas)
# ... record dnsdist getStats() + recursor rec_control get output

dnsperf -s 127.0.0.1 -p 53 \
  -d docs/performance/corpus/control-domains.txt \
  -l 60 -Q 5000 -m udp -O latency-histogram \
  > "$RESULTS_DIR/warm-cache.txt"

# ... snapshot counters AFTER; compute per-layer delta hit ratios

# Phase 3: Saturation (sustained dnsperf; resperf output is not parsed)
if [[ -f "docs/performance/corpus/traffic-corpus-42.txt" ]]; then
  echo "Phase 3: Saturation"
  dnsperf -s 127.0.0.1 -p 53 \
    -d docs/performance/corpus/traffic-corpus-42.txt \
    -l 120 -Q 10000 -m udp -O latency-histogram \
    > "$RESULTS_DIR/saturation.txt"
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
                            Values: cold, warm, saturation, time-to-warm, all

    --clear-mode <mode>     Cache clearing for cold/time-to-warm (default: console)
                              console - non-disruptive console + rec_control clear
                                        (requires DNSDIST_CONSOLE_KEY; fails closed)
                              restart - DESTRUCTIVE opt-in: docker restart both
                                        containers, wait for health, verify floor;
                                        any other value is refused (exit 3)

    --target <host>         DNS server address (default: 127.0.0.1)

    --port <port>           DNS server port (default: 53)

    --corpus <path>         Path to domain corpus file (default: auto-detect)

    --duration <seconds>    Duration per phase in seconds (default: 60)
                            Saturation phase uses 2x this value

    --warm-windows <n>      Time-to-warm: consecutive passing windows (default: 5)

    --warm-window-seconds <s>
                            Time-to-warm: window length (default: 30)

    --ttw-qps <qps>         Time-to-warm: load level (default: 500)

    --no-precache-pause     Skip pausing the admin-ui precache warming job

    --strict-quiesce        Fail (exit 2) when precache cannot be paused

    --output <format>       Output format (default: json)
                            Values: json, markdown, both

    --results-dir <path>    Directory to save results (default: results/)

    --self-test             Offline test suite (no docker, no dnsperf, no network)

    --help, -h              Show help message

    --version, -v           Show script version
```

### Exit Codes

| Code | Meaning | Description |
|------|---------|-------------|
| 0 | SUCCESS | All phases passed, no regressions detected |
| 1 | PHASE_FAILED | One or more phases failed (performance regression or output-parse failure) |
| 2 | PREREQ_FAILED | Prerequisites not met (missing tools, no network access, failed/unverifiable cache clear, missing counter source) |
| 3 | CONFIG_ERROR | Configuration error (invalid arguments, missing files, unrecognized --clear-mode) |

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
  "script_version": "2.0.0",
  "config": {
    "target": "127.0.0.1",
    "port": 53,
    "mode": "all",
    "clear_mode": "console",
    "corpus": "control-domains.txt",
    "duration_seconds": 60
  },
  "environment": {
    "hostname": "powerblockade-01",
    "os": "Linux",
    "kernel": "5.15.0",
    "dnsperf_version": "2.16.0"
  },
  "prerequisites": {
    "dnsperf": { "installed": true, "version": "2.16.0" },
    "jq": { "installed": true },
    "docker": { "installed": true },
    "network_access": { "ok": true, "latency_ms": 1 }
  },
  "stats_sources": {
    "dnsdist": "dnsdist-console",
    "recursor": "rec_control"
  },
  "precache_pause": "paused",
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
        "qps_actual": 997.0,
        "histogram_samples": 59820,
        "percentile_method": "dnsperf -O latency-histogram buckets, bucket upper bound (ms)"
      },
      "counter_deltas": {
        "dnsdist": { "hits": 0, "misses": 59820, "hit_ratio_pct": 0.0 },
        "recursor_packetcache": { "hits": 210, "misses": 50000, "hit_ratio_pct": 0.4 },
        "recursor_recordcache": { "hits": 1500, "misses": 48000, "hit_ratio_pct": 3.0 }
      },
      "thresholds": {
        "p50_limit_ms": 20,
        "p95_limit_ms": 100,
        "p99_limit_ms": 200
      },
      "clear": { "mode": "console", "verified_empty": true }
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
        "qps_actual": 4820.0
      },
      "counter_deltas": {
        "dnsdist": { "hits": 298000, "misses": 1500, "hit_ratio_pct": 99.5 },
        "recursor_packetcache": { "hits": 1200, "misses": 300, "hit_ratio_pct": 80.0 },
        "recursor_recordcache": { "hits": 260, "misses": 40, "hit_ratio_pct": 86.7 }
      },
      "thresholds": {
        "p50_limit_ms": 5,
        "p95_limit_ms": 20,
        "p99_limit_ms": 50,
        "cache_hit_limit_pct": 90
      }
    },
    "saturation": {
      "implemented": true,
      "passed": true,
      "method": "dnsperf-sustained",
      "metrics": {
        "max_qps_sustained": 9810.0,
        "latency_at_50pct_ms": 15.0,
        "error_rate_pct": 2.1
      },
      "thresholds": {
        "min_qps": 5000
      }
    },
    "time_to_warm": {
      "implemented": true,
      "passed": true,
      "metrics": {
        "time_to_warm_s": 187,
        "windows_run": 9,
        "required_consecutive_windows": 5,
        "window_seconds": 30,
        "load_qps": 500
      },
      "windows": [ { "window": 1, "passed": false, "...": "..." } ]
    }
  },
  "baseline": {
    "cache_occupancy": {
      "dnsdist_packetcache": { "entries": 0, "capacity": 500000, "utilization_pct": 0.0 },
      "recursor_recordcache": { "entries": 0, "capacity": 1000000, "utilization_pct": 0.0 },
      "recursor_packetcache": { "entries": 0, "capacity": 500000, "utilization_pct": 0.0 }
    },
    "containers": [ { "name": "powerblockade-dnsdist", "mem_usage": "120MiB", "cpu_pct": "0.4%" } ],
    "host_memory": { "mem_available_kb": 1048576, "swap_free_kb": 0, "swap_total_kb": 0, "pswpin_pages": 0, "pswpout_pages": 0 },
    "recursor_threads_cpu_msec": { "cpu_msec_thread_0": 123456 },
    "dnstap_processor": "healthy"
  },
  "summary": {
    "passed": true,
    "phases_run": 4,
    "phases_passed": 4,
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
| dnsperf >= 2.14.0 | `apt-get install dnsperf` (or build from source) | `dnsperf -V` |
| jq | `apt-get install jq` | `jq --version` |
| docker | host docker access | `docker info` |
| dig | `apt-get install dnsutils` | `dig -v` |
| bc | `apt-get install bc` | `echo 1+1 \| bc` |
| DNSDIST_CONSOLE_KEY | `.env` + recreate dnsdist container | `docker exec powerblockade-dnsdist printenv DNSDIST_CONSOLE_KEY` |

**Environment Variables**:
```bash
# Optional HTTP counter sources (integration branch webservers; when unset
# the harness uses docker exec: console for dnsdist, rec_control for recursor)
export DNSDIST_STATS_URL="http://127.0.0.1:8083"
export DNSDIST_WEB_PASSWORD="..."
export RECURSOR_METRICS_URL="http://127.0.0.1:8082"
export RECURSOR_WEB_PASSWORD="..."

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
| `DNS53_COLD_P99_THRESHOLD_MS` | 200 | Cold cache p99 latency limit (ms) |
| `DNS53_WARM_P50_THRESHOLD_MS` | 5 | Warm cache p50 latency limit (ms) |
| `DNS53_WARM_P95_THRESHOLD_MS` | 20 | Warm cache p95 latency limit (ms) |
| `DNS53_WARM_P99_THRESHOLD_MS` | 50 | Warm cache p99 latency limit (ms) |
| `DNS53_WARM_CACHE_HIT_PCT` | 90 | Warm dnsdist hit ratio minimum (%) |
| `DNS53_SATURATION_MIN_QPS` | 5000 | Saturation minimum sustainable QPS |
| `DNS53_TTW_P99_THRESHOLD_MS` | 50 | Time-to-warm p99 target (ms) |
| `DNS53_TTW_DNSDIST_HIT_PCT` | 90 | Time-to-warm dnsdist hit target (%) |
| `DNS53_TTW_PACKETCACHE_HIT_PCT` | 90 | Time-to-warm recursor packetcache hit target (%) |
| `DNS53_TTW_RECCACHE_HIT_PCT` | 90 | Time-to-warm recursor recordcache hit target (%) |
| `DNS53_TTW_WINDOWS` | 5 | Consecutive passing windows required |
| `DNS53_TTW_WINDOW_SECONDS` | 30 | Window length (s) |
| `DNS53_TTW_QPS` | 500 | Time-to-warm load level (QPS) |
| `DNS53_TTW_MAX_WINDOWS` | 40 | Upper bound on windows before failure |
| `DNS53_RESTART_HEALTH_TIMEOUT` | 180 | restart-mode health wait bound (s) |

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

All commands run inside the recursor container with the compose socket dir:
`docker compose exec recursor rec_control --socket-dir=/var/run/pdns-recursor ...`

```bash
# Flush entire cache (record + packet + negative caches)
rec_control wipe-cache '$'

# Flush specific domain
rec_control wipe-cache example.com

# Flush domain and all subdomains
rec_control wipe-cache example.com$

# Get cache statistics (multiple stats in one call print bare values,
# one per line, in the requested order - "UNKNOWN" means bad stat name)
rec_control get cache-hits cache-misses cache-entries
rec_control get packetcache-hits packetcache-misses packetcache-entries
rec_control get max-cache-entries max-packetcache-entries

# Get all statistics
rec_control get-all

# Health (used by the compose healthcheck)
rec_control ping
```
