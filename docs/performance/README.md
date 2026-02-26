# Performance Documentation Index

> **Purpose**: Index of all DNS performance testing documentation, benchmark scripts, and evidence contracts for PowerBlockade.
> **Audience**: Operators, developers, and QA engineers running performance validation.
> **Last Updated**: 2026-02-26

## Overview

This directory contains documentation for measuring, tuning, and verifying DNS cache performance in PowerBlockade. The performance effort covers:

- **Methodology**: Repeatable benchmark procedures and corpus management
- **Strategy**: Caching architecture decisions and tuning parameters
- **Observability**: Query path tracing and traffic attribution
- **Runbooks**: Operator procedures for staged rollout with regression gates

## Documentation Index

| Document | Purpose | Lines |
|----------|---------|-------|
| [dns-benchmark-methodology.md](dns-benchmark-methodology.md) | Repeatable dnsperf benchmark procedures, corpus construction, CLI contract | 438 |
| [dns-caching-strategy.md](dns-caching-strategy.md) | Cache architecture, tuning matrix, precache policy, retention strategy | 904 |
| [dns-query-path-and-observability.md](dns-query-path-and-observability.md) | Query flow, traffic attribution, metrics pipeline, node lifecycle | 1812 |
| [dns-cache-operations-runbook.md](dns-cache-operations-runbook.md) | Regression gates, logging verification, single-node rollout runbook | 3049 |

## Benchmark Scripts

| Script | Purpose | Location |
|--------|---------|----------|
| `dns53-benchmark.sh` | Main benchmark runner (cold/warm/saturation phases) | `scripts/benchmarks/` |

### Script Contract Summary

```
dns53-benchmark.sh --mode <cold|warm|saturation|all>
                    --target <host>
                    --port <port>
                    --corpus <path>
                    --duration <seconds>
                    --output <json|markdown|both>
                    --results-dir <path>
```

**Exit Codes**:
- `0`: All phases passed
- `1`: One or more phases failed
- `2`: Prerequisites not met
- `3`: Configuration error

## Corpus Files

| File | Purpose | Domains |
|------|---------|---------|
| `corpus/control-domains.txt` | Stable control set for reproducible benchmarks | 120 |

The control corpus is version-controlled and never modified after creation. For realistic testing, generate a corpus from production query logs using the methodology in `dns-benchmark-methodology.md`.

---

## Evidence Contract

Every benchmark run MUST produce a specific set of evidence files for auditability and regression comparison. This contract defines required outputs per mode.

### Required Files Per Benchmark Mode

| Mode | Required Files | Purpose |
|------|----------------|---------|
| **cold** | `benchmark-cold-<id>.json`, `benchmark-cold-<id>.md` | Latency distribution from empty cache |
| **warm** | `benchmark-warm-<id>.json`, `benchmark-warm-<id>.md` | Latency distribution with warmed cache |
| **saturation** | `benchmark-saturation-<id>.json`, `benchmark-saturation-<id>.md` | Max QPS under load |
| **all** | All above files | Complete benchmark suite |

### Required Files Per Regression Check

| Check Type | Required Files | Purpose |
|------------|----------------|---------|
| **Performance Gates** | `benchmark-*.json` | p50/p95/p99 latency, QPS, cache hit ratio |
| **Observability Gates** | `observability-check-<id>.json` | External completeness, internal exclusion |
| **Ingest Parity** | `ingest-parity-<id>.json` | Event count before/after comparison |
| **Logging Regression** | `logging-verification-<id>.json` | Schema integrity, dedupe, blocked continuity |
| **Rollout Decision** | `decision-<id>.md` | GO/HOLD/ROLLBACK with justification |

### File Naming Conventions

```
<type>-<mode>-<benchmark_id>.<ext>
<type>-<check_type>-<benchmark_id>.<ext>
```

**Components**:
- `<type>`: `benchmark`, `observability`, `ingest`, `logging`, `decision`
- `<mode>`: `cold`, `warm`, `saturation` (benchmark files only)
- `<benchmark_id>`: ISO 8601 timestamp + random suffix (e.g., `20260226T143000-a7f3b2`)
- `<ext>`: `json` (machine-readable), `md` (human-readable)

**Examples**:
```
benchmark-cold-20260226T143000-a7f3b2.json
benchmark-warm-20260226T143000-a7f3b2.json
observability-check-20260226T143000-a7f3b2.json
decision-20260226T143000-a7f3b2.md
```

### Minimum Artifacts Per Run

Every benchmark run must include:

1. **Benchmark Results** (JSON + MD)
   - `benchmark-cold-*.json` / `.md`
   - `benchmark-warm-*.json` / `.md`
   - `benchmark-saturation-*.json` / `.md` (if `--mode all`)

2. **Environment Snapshot** (in JSON `environment` key)
   - Hostname, OS, kernel version
   - PowerDNS Recursor version
   - Container resource limits
   - Corpus file hash (SHA256)

3. **Gate Evaluation** (if applicable)
   - `observability-check-*.json`
   - `decision-*.md` (for rollout runs)

4. **Rollback Evidence** (if rollback triggered)
   - `rollback-<id>.md` with commands executed
   - Post-rollback verification results

---

## Evidence Retention Policy

### Retention Periods

| Evidence Type | Retention | Rationale |
|---------------|-----------|-----------|
| **Baseline Results** | 180 days | Long-term comparison for trend analysis |
| **Regression Runs** | 90 days | Sufficient for short-term comparison |
| **Rollback Evidence** | 180 days | Audit trail for incidents |
| **Failed Runs** | 30 days | Debug reference only |
| **Control Corpus** | Indefinite | Version-controlled, never deleted |

### Baseline Comparison

**Baseline Location**: `.sisyphus/baselines/`

**Baseline Naming**:
```
baseline-<version>-<date>.json
```

Example: `baseline-0.4.0-20260215.json`

**Comparison Procedure**:
1. Load current benchmark results JSON
2. Load most recent baseline for same version
3. Compare metrics using tolerance thresholds:
   - Latency: ±10% tolerance, >25% block
   - QPS: ±10% tolerance, >25% block
   - Cache hit ratio: ±5% tolerance, >10% block

**Baseline Promotion**:
- New baselines created after successful release
- Require: All gates passed, 7-day stability period
- Named after release version

### Cleanup Policy

**Automated Cleanup** (run weekly):
```bash
# Delete evidence older than retention period
find .sisyphus/evidence -name "*.json" -mtime +90 -delete
find .sisyphus/evidence -name "*.md" -mtime +90 -delete

# Keep baselines indefinitely
# Keep rollback evidence for 180 days
find .sisyphus/evidence -name "rollback-*" -mtime +180 -delete

# Delete failed runs after 30 days
find .sisyphus/evidence -name "*-failed-*" -mtime +30 -delete
```

**Manual Cleanup Triggers**:
- Disk usage exceeds 1GB in evidence directory
- More than 100 baseline files exist
- Operator requests cleanup

---

## Directory Structure

```
.sisyphus/
├── evidence/                    # QA evidence files (task completion proof)
│   ├── task-1-*.md
│   ├── task-7-*.md
│   └── ...
├── baselines/                   # Performance baselines for comparison
│   ├── baseline-0.4.0-20260215.json
│   └── baseline-0.3.0-20260101.json
└── results/                     # Benchmark run results
    ├── 2026-02-26/
    │   ├── benchmark-cold-*.json
    │   ├── benchmark-warm-*.json
    │   └── ...
    └── ...

docs/performance/
├── README.md                    # This file
├── dns-benchmark-methodology.md # Benchmark procedures
├── dns-caching-strategy.md      # Architecture and tuning
├── dns-query-path-and-observability.md # Query flow and metrics
├── dns-cache-operations-runbook.md # Operator procedures
└── corpus/
    └── control-domains.txt      # Stable test domains

scripts/benchmarks/
└── dns53-benchmark.sh           # Main benchmark runner
```

---

## Quick Reference

### Run Full Benchmark Suite
```bash
./scripts/benchmarks/dns53-benchmark.sh \
  --mode all \
  --target localhost \
  --corpus docs/performance/corpus/control-domains.txt \
  --output both \
  --results-dir .sisyphus/results/$(date +%Y-%m-%d)
```

### Run Regression Gate Check
```bash
# See dns-cache-operations-runbook.md for full script
bash -c 'source docs/performance/dns-cache-operations-runbook.md#regression-gate-check.sh'
```

### Compare Against Baseline
```bash
# Requires jq
baseline=.sisyphus/baselines/baseline-$(cat VERSION)-latest.json
current=.sisyphus/results/$(date +%Y-%m-%d)/benchmark-warm-*.json
jq -n --argfile base "$baseline" --argfile cur "$current" \
  '{p95_diff: ($cur.phases.warm.p95_latency_ms - $base.phases.warm.p95_latency_ms)}'
```

---

## Related Documentation

- [DOCUMENTATION_TRUTH_MAP.md](../DOCUMENTATION_TRUTH_MAP.md) - Documentation ownership and drift risk
- [DESIGN.md](../DESIGN.md) - Technical architecture
- [GETTING_STARTED.md](../GETTING_STARTED.md) - Installation and setup
