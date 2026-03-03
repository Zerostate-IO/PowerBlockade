#!/usr/bin/env bash
#
# dns53-benchmark.sh - PowerBlockade DNS Performance Benchmark Suite
#
# Measures DNS resolution performance across three phases:
#   1. Cold cache - baseline resolution performance
#   2. Warm cache - cached resolution performance  
#   3. Saturation - maximum throughput / stress test
#
# USAGE:
#   ./dns53-benchmark.sh --target 127.0.0.1 --mode all --output json
#   ./dns53-benchmark.sh --help
#
# CONTRACT: See docs/performance/dns-benchmark-methodology.md for full specification
#
# EXIT CODES:
#   0 - All phases passed (no regressions detected)
#   1 - One or more phases failed (performance regression)
#   2 - Prerequisites not met (missing tools, no network access)
#   3 - Configuration error (invalid arguments, missing files)
#
# OUTPUT FORMATS:
#   --output json     - Machine-readable JSON for regression gates
#   --output markdown - Human-readable summary for reports
#   --output both     - Generate both formats
#
# =============================================================================

set -uo pipefail

# =============================================================================
# SCRIPT METADATA
# =============================================================================

readonly SCRIPT_NAME="dns53-benchmark.sh"
readonly SCRIPT_VERSION="1.0.0"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# =============================================================================
# DEFAULT CONFIGURATION
# =============================================================================

# Can be overridden via CLI flags or environment variables
TARGET="${DNS53_BENCHMARK_TARGET:-127.0.0.1}"
PORT="${DNS53_BENCHMARK_PORT:-53}"
MODE="${DNS53_BENCHMARK_MODE:-all}"
CORPUS="${DNS53_BENCHMARK_CORPUS:-}"
DURATION="${DNS53_BENCHMARK_DURATION:-60}"
OUTPUT="${DNS53_BENCHMARK_OUTPUT:-json}"
RESULTS_DIR="${DNS53_BENCHMARK_RESULTS_DIR:-results}"
RECURSOR_API_KEY="${RECURSOR_API_KEY:-}"
RECURSOR_API_URL="${RECURSOR_API_URL:-http://recursor:8082}"

# Default corpus paths (relative to project root)
DEFAULT_CONTROL_CORPUS="docs/performance/corpus/control-domains.txt"
DEFAULT_TRAFFIC_CORPUS="docs/performance/corpus/traffic-corpus-42.txt"

# Performance thresholds (for pass/fail determination)
# These can be overridden via environment variables
COLD_P50_THRESHOLD="${DNS53_COLD_P50_THRESHOLD_MS:-20}"
COLD_P95_THRESHOLD="${DNS53_COLD_P95_THRESHOLD_MS:-100}"
WARM_P50_THRESHOLD="${DNS53_WARM_P50_THRESHOLD_MS:-5}"
WARM_P95_THRESHOLD="${DNS53_WARM_P95_THRESHOLD_MS:-20}"
WARM_CACHE_HIT_THRESHOLD="${DNS53_WARM_CACHE_HIT_PCT:-90}"
SATURATION_MIN_QPS="${DNS53_SATURATION_MIN_QPS:-5000}"

# =============================================================================
# EXIT CODES (Contract)
# =============================================================================

readonly EXIT_SUCCESS=0          # All phases passed
readonly EXIT_PHASE_FAILED=1     # One or more phases failed (regression)
readonly EXIT_PREREQ_FAILED=2    # Prerequisites not met
readonly EXIT_CONFIG_ERROR=3     # Configuration error

# =============================================================================
# OUTPUT SCHEMAS (Contract)
# =============================================================================

# JSON output schema (for regression gates):
# {
#   "benchmark_id": "bm-20260226-001",
#   "run_at": "2026-02-26T14:30:00Z",
#   "script_version": "1.0.0",
#   "config": {
#     "target": "127.0.0.1",
#     "port": 53,
#     "mode": "all",
#     "corpus": "control-domains.txt",
#     "duration_seconds": 60
#   },
#   "environment": {
#     "hostname": "powerblockade-01",
#     "recursor_version": "5.2.0",
#     "os": "Linux",
#     "kernel": "5.15.0"
#   },
#   "prerequisites": {
#     "dnsperf": { "installed": true, "version": "2.15.0" },
#     "rec_control": { "installed": true },
#     "jq": { "installed": true },
#     "network_access": { "ok": true, "latency_ms": 1.2 }
#   },
#   "phases": {
#     "cold_cache": { ... },
#     "warm_cache": { ... },
#     "saturation": { ... }
#   },
#   "summary": {
#     "passed": true,
#     "phases_run": 3,
#     "phases_passed": 3,
#     "phases_failed": 0,
#     "regressions": []
#   }
# }

# Markdown output format (for human reports):
# # DNS53 Benchmark Report
# 
# **Run ID**: bm-20260226-001
# **Date**: 2026-02-26 14:30:00 UTC
# **Target**: 127.0.0.1:53
#
# ## Summary
# | Phase | Status | QPS | p50 | p95 | Notes |
# |-------|--------|-----|-----|-----|-------|
# | Cold Cache | PASS | 997 | 12ms | 45ms | - |
# | Warm Cache | PASS | 4820 | 3ms | 8ms | 95% cache hit |
# | Saturation | PASS | 12500 | 15ms | 62ms | Sustained at 12.5k QPS |
#
# ## Environment
# - Hostname: powerblockade-01
# - Recursor: PowerDNS Recursor 5.2.0
# - OS: Ubuntu 22.04 (Linux 5.15.0)
#
# ## Verdict: ALL PHASES PASSED

# =============================================================================
# COLORS (for terminal output)
# =============================================================================

if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    NC=''
fi

# =============================================================================
# LOGGING FUNCTIONS
# =============================================================================

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_pass()  { echo -e "${GREEN}[PASS]${NC} $*"; }
log_fail()  { echo -e "${RED}[FAIL]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_section() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN} $*${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
}

# =============================================================================
# HELP TEXT (Contract: CLI Interface)
# =============================================================================

show_help() {
    cat << 'EOF'
dns53-benchmark.sh - PowerBlockade DNS Performance Benchmark Suite

USAGE:
    dns53-benchmark.sh [OPTIONS]

OPTIONS:
    --mode <mode>           Benchmark mode(s) to run (default: all)
                            Values: cold, warm, saturation, all

    --target <host>         DNS server address (default: 127.0.0.1)
                            Can also be set via DNS53_BENCHMARK_TARGET env var

    --port <port>           DNS server port (default: 53)
                            Can also be set via DNS53_BENCHMARK_PORT env var

    --corpus <path>         Path to domain corpus file (default: auto-detect)
                            If not specified, uses docs/performance/corpus/control-domains.txt
                            For saturation mode, uses traffic corpus if available

    --duration <seconds>    Duration per phase in seconds (default: 60)
                            Saturation phase uses 2x this value
                            Can also be set via DNS53_BENCHMARK_DURATION env var

    --output <format>       Output format (default: json)
                            Values: json, markdown, both

    --results-dir <path>    Directory to save results (default: results/)
                            Created if it doesn't exist
                            Can also be set via DNS53_BENCHMARK_RESULTS_DIR env var

    --help, -h              Show this help message

    --version, -v           Show version information

ENVIRONMENT VARIABLES:
    DNS53_BENCHMARK_TARGET     Default target host
    DNS53_BENCHMARK_PORT       Default target port
    DNS53_BENCHMARK_MODE       Default mode
    DNS53_BENCHMARK_CORPUS     Default corpus path
    DNS53_BENCHMARK_DURATION   Default duration
    DNS53_BENCHMARK_OUTPUT     Default output format
    DNS53_BENCHMARK_RESULTS_DIR Default results directory
    RECURSOR_API_KEY           API key for recursor cache operations
    RECURSOR_API_URL           Recursor API endpoint (default: http://recursor:8082)

    # Thresholds (for pass/fail determination):
    DNS53_COLD_P50_THRESHOLD_MS    Cold cache p50 latency threshold (default: 20)
    DNS53_COLD_P95_THRESHOLD_MS    Cold cache p95 latency threshold (default: 100)
    DNS53_WARM_P50_THRESHOLD_MS    Warm cache p50 latency threshold (default: 5)
    DNS53_WARM_P95_THRESHOLD_MS    Warm cache p95 latency threshold (default: 20)
    DNS53_WARM_CACHE_HIT_PCT       Warm cache hit ratio threshold (default: 90)
    DNS53_SATURATION_MIN_QPS       Minimum QPS for saturation pass (default: 5000)

EXIT CODES:
    0    All phases passed (no regressions detected)
    1    One or more phases failed (performance regression)
    2    Prerequisites not met (missing tools, no network access)
    3    Configuration error (invalid arguments, missing files)

EXAMPLES:
    # Run all benchmarks against local DNS server
    ./dns53-benchmark.sh --target 127.0.0.1 --mode all

    # Run only cold cache benchmark with custom corpus
    ./dns53-benchmark.sh --mode cold --corpus ./my-domains.txt

    # Generate both JSON and Markdown reports
    ./dns53-benchmark.sh --mode all --output both --results-dir ./benchmark-results

    # Quick warm cache test (30 seconds)
    ./dns53-benchmark.sh --mode warm --duration 30

PREREQUISITES:
    - dnsperf  (DNS performance testing tool)
    - rec_control (PowerDNS Recursor control utility, for cache operations)
    - jq (JSON processor)
    - Network access to target DNS server

    Install on Ubuntu/Debian:
        apt-get install dnsperf jq

    Install on macOS:
        brew install dnsperf jq

DOCUMENTATION:
    Full methodology: docs/performance/dns-benchmark-methodology.md

EOF
}

show_version() {
    echo "dns53-benchmark.sh version ${SCRIPT_VERSION}"
}

# =============================================================================
# PREREQUISITE CHECKS (Contract)
# =============================================================================

check_prerequisites() {
    local errors=0
    local prereq_json="{"

    log_section "Prerequisite Checks"

    # Check dnsperf
    if command -v dnsperf &>/dev/null; then
        local dnsperf_version
        dnsperf_version=$(dnsperf -V 2>&1 | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown")
        log_pass "dnsperf installed (version: $dnsperf_version)"
        prereq_json+="\"dnsperf\": {\"installed\": true, \"version\": \"$dnsperf_version\"}, "
    else
        log_fail "dnsperf not installed"
        prereq_json+="\"dnsperf\": {\"installed\": false}, "
        ((errors++))
    fi

    # Check rec_control (optional for some modes)
    if command -v rec_control &>/dev/null; then
        log_pass "rec_control available"
        prereq_json+="\"rec_control\": {\"installed\": true}, "
    else
        if [[ "$MODE" == "all" || "$MODE" == "cold" || "$MODE" == "warm" ]]; then
            log_warn "rec_control not found - cache operations will use fallback methods"
        fi
        prereq_json+="\"rec_control\": {\"installed\": false}, "
    fi

    # Check jq
    if command -v jq &>/dev/null; then
        log_pass "jq installed"
        prereq_json+="\"jq\": {\"installed\": true}, "
    else
        log_fail "jq not installed"
        prereq_json+="\"jq\": {\"installed\": false}, "
        errors=$((errors + 1))
    fi

    # Check bc (required for threshold calculations)
    if command -v bc &>/dev/null; then
        log_pass "bc installed"
        prereq_json+="\"bc\": {\"installed\": true}, "
    else
        log_fail "bc not installed (required for threshold calculations)"
        prereq_json+="\"bc\": {\"installed\": false}, "
        errors=$((errors + 1))
    fi

    # Check network access to target
    local latency_ms
    latency_ms=$(check_network_access)
    if [[ $? -eq 0 ]]; then
        log_pass "Network access to $TARGET:$PORT (latency: ${latency_ms}ms)"
        prereq_json+="\"network_access\": {\"ok\": true, \"latency_ms\": $latency_ms}"
    else
        log_fail "Cannot reach $TARGET:$PORT"
        prereq_json+="\"network_access\": {\"ok\": false}"
        ((errors++))
    fi

    prereq_json+="}"

    # Store for JSON output
    PREREQ_JSON="$prereq_json"

    if [[ $errors -gt 0 ]]; then
        return $EXIT_PREREQ_FAILED
    fi

    return 0
}

check_network_access() {
    local start_ns end_ns latency_ns latency_ms

    # Use dig with timeout to check connectivity
    start_ns=$(date +%s%N)
    if ! dig +short +time=2 +tries=1 "@${TARGET}" -p "${PORT}" google.com A &>/dev/null; then
        return 1
    fi
    end_ns=$(date +%s%N)

    latency_ns=$((end_ns - start_ns))
    latency_ms=$((latency_ns / 1000000))
    echo "$latency_ms"
    return 0
}

# =============================================================================
# CONFIGURATION VALIDATION (Contract)
# =============================================================================

validate_config() {
    local errors=0

    log_section "Configuration Validation"

    # Validate mode
    case "$MODE" in
        cold|warm|saturation|all)
            log_pass "Mode: $MODE"
            ;;
        *)
            log_fail "Invalid mode: $MODE (expected: cold, warm, saturation, all)"
            ((errors++))
            ;;
    esac

    # Validate output format
    case "$OUTPUT" in
        json|markdown|both)
            log_pass "Output format: $OUTPUT"
            ;;
        *)
            log_fail "Invalid output format: $OUTPUT (expected: json, markdown, both)"
            ((errors++))
            ;;
    esac

    # Validate duration
    if ! [[ "$DURATION" =~ ^[0-9]+$ ]] || [[ "$DURATION" -lt 1 ]]; then
        log_fail "Invalid duration: $DURATION (expected: positive integer)"
        ((errors++))
    else
        log_pass "Duration: ${DURATION}s per phase"
    fi

    # Validate corpus file
    if [[ -n "$CORPUS" ]]; then
        if [[ -f "$CORPUS" ]]; then
            log_pass "Corpus: $CORPUS"
        else
            log_fail "Corpus file not found: $CORPUS"
            ((errors++))
        fi
    else
        # Auto-detect corpus
        if [[ -f "${PROJECT_ROOT}/${DEFAULT_CONTROL_CORPUS}" ]]; then
            CORPUS="${PROJECT_ROOT}/${DEFAULT_CONTROL_CORPUS}"
            log_pass "Corpus (auto-detected): $CORPUS"
        else
            log_fail "No corpus specified and default not found: ${DEFAULT_CONTROL_CORPUS}"
            log_info "Create a corpus file or specify --corpus <path>"
            ((errors++))
        fi
    fi

    # Validate target is reachable (already done in prerequisites, but double-check)
    if [[ -z "$TARGET" ]]; then
        log_fail "Target not specified"
        ((errors++))
    else
        log_pass "Target: ${TARGET}:${PORT}"
    fi

    # Create results directory if needed
    mkdir -p "$RESULTS_DIR" 2>/dev/null || {
        log_fail "Cannot create results directory: $RESULTS_DIR"
        ((errors++))
    }

    if [[ $errors -gt 0 ]]; then
        return $EXIT_CONFIG_ERROR
    fi

    return 0
}

# =============================================================================
# BENCHMARK PHASE RESULT STORAGE
# =============================================================================

# Global variables to store phase results (for JSON aggregation)
COLD_CACHE_RESULT="null"
WARM_CACHE_RESULT="null"
SATURATION_RESULT="null"
PHASES_RUN=0
PHASES_PASSED=0
PHASES_FAILED=0
REGRESSIONS=()

# =============================================================================
# CACHE OPERATIONS
# =============================================================================

flush_recursor_cache() {
    log_info "Flushing recursor cache..."
    
    # Try rec_control first
    if command -v rec_control &>/dev/null; then
        if rec_control wipe-cache '$' &>/dev/null; then
            log_pass "Cache flushed via rec_control"
            return 0
        fi
    fi
    
    # Try API flush
    if [[ -n "$RECURSOR_API_KEY" ]]; then
        local api_result
        api_result=$(curl -sf -X PUT "${RECURSOR_API_URL}/api/v1/servers/localhost/cache/flush" \
            -H "X-API-Key: ${RECURSOR_API_KEY}" 2>/dev/null) && {
            log_pass "Cache flushed via API"
            return 0
        }
    fi
    
    log_warn "Could not flush cache - results may include cached responses"
    return 1
}

get_cache_stats() {
    # Returns JSON with cache-hits, cache-misses, cache-entries
    local cache_json='{"cache_hits": null, "cache_misses": null, "cache_entries": null}'
    
    # Try rec_control first
    if command -v rec_control &>/dev/null; then
        local hits misses entries
        hits=$(rec_control get cache-hits 2>/dev/null || echo "null")
        misses=$(rec_control get cache-misses 2>/dev/null || echo "null")
        entries=$(rec_control get cache-entries 2>/dev/null || echo "null")
        
        if [[ "$hits" != "null" && "$misses" != "null" ]]; then
            cache_json=$(jq -n \
                --argjson hits "$hits" \
                --argjson misses "$misses" \
                --argjson entries "$entries" \
                '{cache_hits: $hits, cache_misses: $misses, cache_entries: $entries}')
            echo "$cache_json"
            return 0
        fi
    fi
    
    # Try API
    if [[ -n "$RECURSOR_API_KEY" ]]; then
        local stats
        stats=$(curl -sf "${RECURSOR_API_URL}/api/v1/servers/localhost/statistics" \
            -H "X-API-Key: ${RECURSOR_API_KEY}" 2>/dev/null) && {
            cache_json=$(echo "$stats" | jq '{
                cache_hits: (.[] | select(.name == "cache-hits") | .value),
                cache_misses: (.[] | select(.name == "cache-misses") | .value),
                cache_entries: (.[] | select(.name == "cache-entries") | .value)
            }' 2>/dev/null) && {
                echo "$cache_json"
                return 0
            }
        }
    fi
    
    echo "$cache_json"
    return 1
}

# =============================================================================
# DNSPERF EXECUTION AND PARSING
# =============================================================================

run_dnsperf() {
    local target="$1"
    local port="$2"
    local corpus="$3"
    local duration="$4"
    local qps="$5"
    local output_file="$6"
    
    # Check if dnsperf supports -o json (version 2.14+)
    local dnsperf_supports_json=false
    if dnsperf -h 2>&1 | grep -q '\-o'; then
        dnsperf_supports_json=true
    fi
    
    if [[ "$dnsperf_supports_json" == "true" ]]; then
        dnsperf -s "$target" -p "$port" \
            -d "$corpus" \
            -l "$duration" \
            -Q "$qps" \
            -m udp \
            -o json \
            > "$output_file" 2>/dev/null
    else
        # Fallback: run dnsperf and capture text output, then convert to JSON
        local text_output
        text_output=$(dnsperf -s "$target" -p "$port" \
            -d "$corpus" \
            -l "$duration" \
            -Q "$qps" \
            -m udp 2>&1)
        
        # Parse text output and create JSON
        local queries_sent queries_completed queries_lost avg_latency
        local latency_variance qps_actual
        
        queries_sent=$(echo "$text_output" | grep -oP 'Queries sent:\s*\K[0-9]+' || echo "0")
        queries_completed=$(echo "$text_output" | grep -oP 'Queries completed:\s*\K[0-9]+' || echo "0")
        queries_lost=$(echo "$text_output" | grep -oP 'Queries lost:\s*\K[0-9]+' || echo "0")
        avg_latency=$(echo "$text_output" | grep -oP 'Avg latency:\s*\K[0-9.]+' || echo "0")
        qps_actual=$(echo "$text_output" | grep -oP 'QPS run:\s*\K[0-9.]+' || \
                     echo "$text_output" | grep -oP 'QPS:\s*\K[0-9.]+' || echo "0")
        
        # Create JSON output
        jq -n \
            --argjson queries_sent "$queries_sent" \
            --argjson queries_completed "$queries_completed" \
            --argjson queries_lost "$queries_lost" \
            --argjson avg_latency "$avg_latency" \
            --argjson qps_actual "$qps_actual" \
            '{
                "queries_sent": $queries_sent,
                "queries_completed": $queries_completed,
                "queries_lost": $queries_lost,
                "avg_latency_ms": $avg_latency,
                "qps_actual": $qps_actual,
                "p50_latency_ms": null,
                "p95_latency_ms": null,
                "p99_latency_ms": null,
                "min_latency_ms": null,
                "max_latency_ms": null,
                "note": "Parsed from text output - percentile data unavailable"
            }' > "$output_file"
    fi
    
    return $?
}

run_resperf() {
    local target="$1"
    local port="$2"
    local corpus="$3"
    local max_qps="$4"
    local output_file="$5"
    
    # Check if resperf is available
    if ! command -v resperf &>/dev/null; then
        log_warn "resperf not available, using dnsperf fallback for saturation"
        return 1
    fi
    
    # Check if resperf supports -o json
    local resperf_supports_json=false
    if resperf -h 2>&1 | grep -q '\-o'; then
        resperf_supports_json=true
    fi
    
    if [[ "$resperf_supports_json" == "true" ]]; then
        resperf -s "$target" -p "$port" \
            -d "$corpus" \
            -m "$max_qps" \
            -i 1 \
            -o json \
            > "$output_file" 2>/dev/null
    else
        # Fallback: text output
        local text_output
        text_output=$(resperf -s "$target" -p "$port" \
            -d "$corpus" \
            -m "$max_qps" \
            -i 1 2>&1)
        
        local max_sustained error_rate
        max_sustained=$(echo "$text_output" | grep -oP 'Max throughput:\s*\K[0-9.]+' || \
                        echo "$text_output" | grep -oP 'Maximum QPS:\s*\K[0-9.]+' || echo "0")
        error_rate=$(echo "$text_output" | grep -oP 'Lost at max:\s*\K[0-9.]+' || echo "0")
        
        jq -n \
            --argjson max_qps "$max_sustained" \
            --argjson error_rate "$error_rate" \
            '{
                "max_qps_sustained": $max_qps,
                "error_rate_pct": $error_rate,
                "note": "Parsed from text output"
            }' > "$output_file"
    fi
    
    return $?
}

# =============================================================================
# BENCHMARK PHASE IMPLEMENTATIONS
# =============================================================================

run_cold_cache_phase() {
    log_section "Phase 1: Cold Cache Benchmark"
    
    local phase_result
    local passed=true
    local regressions=()
    
    # Store cache stats before flush
    local pre_flush_stats
    pre_flush_stats=$(get_cache_stats)
    
    # Step 1: Flush cache
    flush_recursor_cache
    sleep 2  # Wait for cache to settle
    
    # Step 2: Run dnsperf benchmark
    local dnsperf_output="${RESULTS_DIR}/cold-cache-raw-$$.json"
    log_info "Running dnsperf for ${DURATION}s at 1000 QPS..."
    
    if ! run_dnsperf "$TARGET" "$PORT" "$CORPUS" "$DURATION" 1000 "$dnsperf_output"; then
        log_fail "dnsperf execution failed"
        COLD_CACHE_RESULT=$(jq -n '{
            implemented: true,
            passed: false,
            error: "dnsperf execution failed"
        }')
        ((PHASES_RUN++))
        ((PHASES_FAILED++))
        REGRESSIONS+=("cold_cache: dnsperf_failed")
        return $EXIT_PHASE_FAILED
    fi
    
    # Step 3: Parse results
    local queries_sent queries_completed queries_lost avg_latency p50 p95 p99 qps_actual
    
    if [[ -f "$dnsperf_output" ]]; then
        queries_sent=$(jq -r '.queries_sent // 0' "$dnsperf_output")
        queries_completed=$(jq -r '.queries_completed // 0' "$dnsperf_output")
        queries_lost=$(jq -r '.queries_lost // 0' "$dnsperf_output")
        avg_latency=$(jq -r '.avg_latency_ms // 0' "$dnsperf_output")
        p50=$(jq -r '.p50_latency_ms // 0' "$dnsperf_output")
        p95=$(jq -r '.p95_latency_ms // 0' "$dnsperf_output")
        p99=$(jq -r '.p99_latency_ms // 0' "$dnsperf_output")
        qps_actual=$(jq -r '.qps_actual // 0' "$dnsperf_output")
    else
        log_fail "dnsperf output file not found"
        COLD_CACHE_RESULT=$(jq -n '{implemented: true, passed: false, error: "output_missing"}')
        ((PHASES_RUN++))
        ((PHASES_FAILED++))
        return $EXIT_PHASE_FAILED
    fi
    
    # Step 4: Evaluate against thresholds
    if [[ "$p50" != "null" && -n "$p50" ]] && (( $(echo "$p50 > $COLD_P50_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
        log_fail "p50 latency (${p50}ms) exceeds threshold (${COLD_P50_THRESHOLD}ms)"
        passed=false
        regressions+=("p50_latency_exceeded")
    fi
    
    if [[ "$p95" != "null" && -n "$p95" ]] && (( $(echo "$p95 > $COLD_P95_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
        log_fail "p95 latency (${p95}ms) exceeds threshold (${COLD_P95_THRESHOLD}ms)"
        passed=false
        regressions+=("p95_latency_exceeded")
    fi
    
    # Calculate success rate
    local success_rate=0
    if [[ "$queries_sent" -gt 0 ]]; then
        success_rate=$(echo "scale=2; $queries_completed * 100 / $queries_sent" | bc)
    fi
    
    # Step 5: Build result JSON
    local reg_array
    if [[ ${#regressions[@]} -gt 0 ]]; then
        reg_array=$(printf '%s\n' "${regressions[@]}" | jq -R . | jq -s .)
    else
        reg_array="[]"
    fi
    
    COLD_CACHE_RESULT=$(jq -n \
        --argjson implemented true \
        --argjson passed "$passed" \
        --argjson queries_sent "$queries_sent" \
        --argjson queries_completed "$queries_completed" \
        --argjson queries_lost "$queries_lost" \
        --argjson avg_latency "$avg_latency" \
        --argjson p50 "$p50" \
        --argjson p95 "$p95" \
        --argjson p99 "$p99" \
        --argjson qps_actual "$qps_actual" \
        --argjson success_rate "$success_rate" \
        --argjson p50_limit "$COLD_P50_THRESHOLD" \
        --argjson p95_limit "$COLD_P95_THRESHOLD" \
        --argjson reg "$reg_array" \
        '{
            implemented: $implemented,
            passed: $passed,
            metrics: {
                queries_sent: $queries_sent,
                queries_completed: $queries_completed,
                queries_lost: $queries_lost,
                avg_latency_ms: $avg_latency,
                p50_latency_ms: $p50,
                p95_latency_ms: $p95,
                p99_latency_ms: $p99,
                qps_actual: $qps_actual,
                success_rate_pct: $success_rate
            },
            thresholds: {
                p50_limit_ms: $p50_limit,
                p95_limit_ms: $p95_limit
            },
            regressions: $reg
        }')
    
    # Update counters
    ((PHASES_RUN++))
    if [[ "$passed" == "true" ]]; then
        log_pass "Cold cache phase passed"
        ((PHASES_PASSED++))
    else
        log_fail "Cold cache phase failed"
        ((PHASES_FAILED++))
        REGRESSIONS+=("cold_cache")
    fi
    
    # Cleanup
    rm -f "$dnsperf_output" 2>/dev/null
    
    if [[ "$passed" == "true" ]]; then
        return 0
    else
        return $EXIT_PHASE_FAILED
    fi
}

run_warm_cache_phase() {
    log_section "Phase 2: Warm Cache Benchmark"
    
    local passed=true
    local regressions=()
    
    # Step 1: Warmup - run corpus 3x to prime cache
    log_info "Priming cache with 3x warmup runs..."
    for i in 1 2 3; do
        run_dnsperf "$TARGET" "$PORT" "$CORPUS" 30 500 "/dev/null" 2>/dev/null || true
        sleep 1
    done
    
    # Get cache stats before benchmark
    local pre_stats
    pre_stats=$(get_cache_stats)
    
    # Step 2: Run dnsperf at higher QPS
    local dnsperf_output="${RESULTS_DIR}/warm-cache-raw-$$.json"
    log_info "Running dnsperf for ${DURATION}s at 5000 QPS..."
    
    if ! run_dnsperf "$TARGET" "$PORT" "$CORPUS" "$DURATION" 5000 "$dnsperf_output"; then
        log_fail "dnsperf execution failed"
        WARM_CACHE_RESULT=$(jq -n '{
            implemented: true,
            passed: false,
            error: "dnsperf execution failed"
        }')
        ((PHASES_RUN++))
        ((PHASES_FAILED++))
        REGRESSIONS+=("warm_cache: dnsperf_failed")
        return $EXIT_PHASE_FAILED
    fi
    
    # Step 3: Get post-benchmark cache stats
    local post_stats
    post_stats=$(get_cache_stats)
    
    # Calculate cache hit ratio
    local cache_hits cache_misses cache_hit_ratio=0
    cache_hits=$(echo "$post_stats" | jq -r '.cache_hits // 0')
    cache_misses=$(echo "$post_stats" | jq -r '.cache_misses // 0')
    
    if [[ "$cache_hits" != "null" && "$cache_misses" != "null" ]]; then
        local total=$((cache_hits + cache_misses))
        if [[ $total -gt 0 ]]; then
            cache_hit_ratio=$(echo "scale=4; $cache_hits * 100 / $total" | bc)
        fi
    fi
    
    # Step 4: Parse dnsperf results
    local queries_sent queries_completed queries_lost avg_latency p50 p95 p99 qps_actual
    
    if [[ -f "$dnsperf_output" ]]; then
        queries_sent=$(jq -r '.queries_sent // 0' "$dnsperf_output")
        queries_completed=$(jq -r '.queries_completed // 0' "$dnsperf_output")
        queries_lost=$(jq -r '.queries_lost // 0' "$dnsperf_output")
        avg_latency=$(jq -r '.avg_latency_ms // 0' "$dnsperf_output")
        p50=$(jq -r '.p50_latency_ms // 0' "$dnsperf_output")
        p95=$(jq -r '.p95_latency_ms // 0' "$dnsperf_output")
        p99=$(jq -r '.p99_latency_ms // 0' "$dnsperf_output")
        qps_actual=$(jq -r '.qps_actual // 0' "$dnsperf_output")
    else
        log_fail "dnsperf output file not found"
        WARM_CACHE_RESULT=$(jq -n '{implemented: true, passed: false, error: "output_missing"}')
        ((PHASES_RUN++))
        ((PHASES_FAILED++))
        return $EXIT_PHASE_FAILED
    fi
    
    # Step 5: Evaluate against thresholds
    if [[ "$p50" != "null" && -n "$p50" ]] && (( $(echo "$p50 > $WARM_P50_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
        log_fail "p50 latency (${p50}ms) exceeds threshold (${WARM_P50_THRESHOLD}ms)"
        passed=false
        regressions+=("p50_latency_exceeded")
    fi
    
    if [[ "$p95" != "null" && -n "$p95" ]] && (( $(echo "$p95 > $WARM_P95_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
        log_fail "p95 latency (${p95}ms) exceeds threshold (${WARM_P95_THRESHOLD}ms)"
        passed=false
        regressions+=("p95_latency_exceeded")
    fi
    
    # Check cache hit ratio
    if (( $(echo "$cache_hit_ratio < $WARM_CACHE_HIT_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
        log_fail "Cache hit ratio (${cache_hit_ratio}%) below threshold (${WARM_CACHE_HIT_THRESHOLD}%)"
        passed=false
        regressions+=("cache_hit_ratio_low")
    fi
    
    # Calculate success rate
    local success_rate=0
    if [[ "$queries_sent" -gt 0 ]]; then
        success_rate=$(echo "scale=2; $queries_completed * 100 / $queries_sent" | bc)
    fi
    
    # Step 6: Build result JSON
    local reg_array
    if [[ ${#regressions[@]} -gt 0 ]]; then
        reg_array=$(printf '%s\n' "${regressions[@]}" | jq -R . | jq -s .)
    else
        reg_array="[]"
    fi
    
    WARM_CACHE_RESULT=$(jq -n \
        --argjson implemented true \
        --argjson passed "$passed" \
        --argjson queries_sent "$queries_sent" \
        --argjson queries_completed "$queries_completed" \
        --argjson queries_lost "$queries_lost" \
        --argjson avg_latency "$avg_latency" \
        --argjson p50 "$p50" \
        --argjson p95 "$p95" \
        --argjson p99 "$p99" \
        --argjson qps_actual "$qps_actual" \
        --argjson success_rate "$success_rate" \
        --argjson cache_hit_ratio "$cache_hit_ratio" \
        --argjson cache_hits "$cache_hits" \
        --argjson cache_misses "$cache_misses" \
        --argjson p50_limit "$WARM_P50_THRESHOLD" \
        --argjson p95_limit "$WARM_P95_THRESHOLD" \
        --argjson cache_hit_limit "$WARM_CACHE_HIT_THRESHOLD" \
        --argjson reg "$reg_array" \
        '{
            implemented: $implemented,
            passed: $passed,
            metrics: {
                queries_sent: $queries_sent,
                queries_completed: $queries_completed,
                queries_lost: $queries_lost,
                avg_latency_ms: $avg_latency,
                p50_latency_ms: $p50,
                p95_latency_ms: $p95,
                p99_latency_ms: $p99,
                qps_actual: $qps_actual,
                success_rate_pct: $success_rate,
                cache_hit_ratio: $cache_hit_ratio,
                cache_hits: $cache_hits,
                cache_misses: $cache_misses
            },
            thresholds: {
                p50_limit_ms: $p50_limit,
                p95_limit_ms: $p95_limit,
                cache_hit_limit_pct: $cache_hit_limit
            },
            regressions: $reg
        }')
    
    # Update counters
    ((PHASES_RUN++))
    if [[ "$passed" == "true" ]]; then
        log_pass "Warm cache phase passed"
        ((PHASES_PASSED++))
    else
        log_fail "Warm cache phase failed"
        ((PHASES_FAILED++))
        REGRESSIONS+=("warm_cache")
    fi
    
    # Cleanup
    rm -f "$dnsperf_output" 2>/dev/null
    
    if [[ "$passed" == "true" ]]; then
        return 0
    else
        return $EXIT_PHASE_FAILED
    fi
}

run_saturation_phase() {
    log_section "Phase 3: Saturation Benchmark"
    
    local passed=true
    local regressions=()
    local saturation_duration=$((DURATION * 2))
    local max_qps_target=100000
    
    # Check for traffic corpus (preferred for saturation)
    local saturation_corpus="$CORPUS"
    local traffic_corpus="${PROJECT_ROOT}/${DEFAULT_TRAFFIC_CORPUS}"
    if [[ -f "$traffic_corpus" ]]; then
        saturation_corpus="$traffic_corpus"
        log_info "Using traffic corpus for saturation: $(basename "$traffic_corpus")"
    fi
    
    local output_file="${RESULTS_DIR}/saturation-raw-$$.json"
    local max_sustained=0
    local error_rate=0
    local latency_at_50=0
    
    # Try resperf first (better for saturation testing)
    if command -v resperf &>/dev/null; then
        log_info "Running resperf for ${saturation_duration}s (max QPS: ${max_qps_target})..."
        
        if run_resperf "$TARGET" "$PORT" "$saturation_corpus" "$max_qps_target" "$output_file"; then
            max_sustained=$(jq -r '.max_qps_sustained // 0' "$output_file" 2>/dev/null || echo "0")
            error_rate=$(jq -r '.error_rate_pct // 0' "$output_file" 2>/dev/null || echo "0")
        else
            log_warn "resperf failed, falling back to dnsperf"
            rm -f "$output_file" 2>/dev/null
        fi
    fi
    
    # Fallback to dnsperf if resperf unavailable or failed
    if [[ ! -f "$output_file" ]] || [[ "$max_sustained" == "0" ]]; then
        log_info "Running dnsperf for ${saturation_duration}s at 10000 QPS (saturation)..."
        
        if run_dnsperf "$TARGET" "$PORT" "$saturation_corpus" "$saturation_duration" 10000 "$output_file"; then
            local qps_actual queries_sent queries_completed queries_lost
            qps_actual=$(jq -r '.qps_actual // 0' "$output_file" 2>/dev/null || echo "0")
            queries_sent=$(jq -r '.queries_sent // 0' "$output_file" 2>/dev/null || echo "0")
            queries_completed=$(jq -r '.queries_completed // 0' "$output_file" 2>/dev/null || echo "0")
            queries_lost=$(jq -r '.queries_lost // 0' "$output_file" 2>/dev/null || echo "0")
            
            max_sustained="$qps_actual"
            latency_at_50=$(jq -r '.p50_latency_ms // 0' "$output_file" 2>/dev/null || echo "0")
            
            if [[ "$queries_sent" -gt 0 ]]; then
                error_rate=$(echo "scale=2; $queries_lost * 100 / $queries_sent" | bc)
            fi
        else
            log_fail "dnsperf saturation execution failed"
            SATURATION_RESULT=$(jq -n '{
                implemented: true,
                passed: false,
                error: "benchmark_execution_failed"
            }')
            ((PHASES_RUN++))
            ((PHASES_FAILED++))
            REGRESSIONS+=("saturation: execution_failed")
            return $EXIT_PHASE_FAILED
        fi
    fi
    
    # Evaluate against thresholds
    if (( $(echo "$max_sustained < $SATURATION_MIN_QPS" | bc -l 2>/dev/null || echo 0) )); then
        log_fail "Max sustained QPS (${max_sustained}) below threshold (${SATURATION_MIN_QPS})"
        passed=false
        regressions+=("qps_below_threshold")
    fi
    
    if (( $(echo "$error_rate > 5" | bc -l 2>/dev/null || echo 0) )); then
        log_fail "Error rate (${error_rate}%) exceeds 5% threshold"
        passed=false
        regressions+=("error_rate_high")
    fi
    
    # Build result JSON
    local reg_array
    if [[ ${#regressions[@]} -gt 0 ]]; then
        reg_array=$(printf '%s\n' "${regressions[@]}" | jq -R . | jq -s .)
    else
        reg_array="[]"
    fi
    
    SATURATION_RESULT=$(jq -n \
        --argjson implemented true \
        --argjson passed "$passed" \
        --argjson max_qps "$max_sustained" \
        --argjson error_rate "$error_rate" \
        --argjson latency_at_50 "$latency_at_50" \
        --argjson duration "$saturation_duration" \
        --argjson min_qps "$SATURATION_MIN_QPS" \
        --argjson reg "$reg_array" \
        '{
            implemented: $implemented,
            passed: $passed,
            metrics: {
                max_qps_sustained: $max_qps,
                latency_at_50pct_ms: $latency_at_50,
                error_rate_pct: $error_rate,
                duration_seconds: $duration
            },
            thresholds: {
                min_qps: $min_qps
            },
            regressions: $reg
        }')
    
    # Update counters
    ((PHASES_RUN++))
    if [[ "$passed" == "true" ]]; then
        log_pass "Saturation phase passed"
        ((PHASES_PASSED++))
    else
        log_fail "Saturation phase failed"
        ((PHASES_FAILED++))
        REGRESSIONS+=("saturation")
    fi
    
    # Cleanup
    rm -f "$output_file" 2>/dev/null
    
    if [[ "$passed" == "true" ]]; then
        return 0
    else
        return $EXIT_PHASE_FAILED
    fi
}

# =============================================================================
# OUTPUT GENERATION (Contract)
# =============================================================================

generate_json_output() {
    local benchmark_id="bm-$(date +%Y%m%d-%H%M%S)"
    local run_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    # Build regressions array from global REGRESSIONS
    local reg_array
    if [[ ${#REGRESSIONS[@]} -gt 0 ]]; then
        reg_array=$(printf '%s\n' "${REGRESSIONS[@]}" | jq -R . | jq -s .)
    else
        reg_array="[]"
    fi
    
    # Determine overall passed status
    local overall_passed=true
    if [[ $PHASES_FAILED -gt 0 ]]; then
        overall_passed=false
    fi
    
    # Build phases JSON
    local phases_json
    phases_json=$(jq -n \
        --argjson cold "$COLD_CACHE_RESULT" \
        --argjson warm "$WARM_CACHE_RESULT" \
        --argjson saturation "$SATURATION_RESULT" \
        '{
            cold_cache: $cold,
            warm_cache: $warm,
            saturation: $saturation
        }')
    
    # Build complete JSON output
    jq -n \
        --arg benchmark_id "$benchmark_id" \
        --arg run_at "$run_at" \
        --arg script_version "$SCRIPT_VERSION" \
        --arg target "$TARGET" \
        --argjson port "$PORT" \
        --arg mode "$MODE" \
        --arg corpus "$(basename "$CORPUS")" \
        --argjson duration "$DURATION" \
        --arg hostname "$(hostname)" \
        --arg os "$(uname -s)" \
        --arg kernel "$(uname -r)" \
        --argjson prereq "$PREREQ_JSON" \
        --argjson phases "$phases_json" \
        --argjson passed "$overall_passed" \
        --argjson phases_run "$PHASES_RUN" \
        --argjson phases_passed "$PHASES_PASSED" \
        --argjson phases_failed "$PHASES_FAILED" \
        --argjson regressions "$reg_array" \
        '{
            benchmark_id: $benchmark_id,
            run_at: $run_at,
            script_version: $script_version,
            config: {
                target: $target,
                port: $port,
                mode: $mode,
                corpus: $corpus,
                duration_seconds: $duration
            },
            environment: {
                hostname: $hostname,
                os: $os,
                kernel: $kernel
            },
            prerequisites: $prereq,
            phases: $phases,
            summary: {
                passed: $passed,
                phases_run: $phases_run,
                phases_passed: $phases_passed,
                phases_failed: $phases_failed,
                regressions: $regressions
            }
        }'
}

generate_markdown_output() {
    local benchmark_id="bm-$(date +%Y%m%d-%H%M%S)"
    local run_at=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
    
    # Build phase table rows
    local cold_status="SKIP"
    local cold_qps="-"
    local cold_p50="-"
    local cold_p95="-"
    local cold_notes=""
    
    local warm_status="SKIP"
    local warm_qps="-"
    local warm_p50="-"
    local warm_p95="-"
    local warm_notes=""
    
    local sat_status="SKIP"
    local sat_qps="-"
    local sat_p50="-"
    local sat_p95="-"
    local sat_notes=""
    
    # Extract cold cache data
    if [[ "$COLD_CACHE_RESULT" != "null" ]]; then
        if echo "$COLD_CACHE_RESULT" | jq -e '.passed == true' &>/dev/null; then
            cold_status="PASS"
        else
            cold_status="FAIL"
        fi
        cold_qps=$(echo "$COLD_CACHE_RESULT" | jq -r '.metrics.qps_actual // "-"')
        cold_p50=$(echo "$COLD_CACHE_RESULT" | jq -r '.metrics.p50_latency_ms // "-"')
        cold_p95=$(echo "$COLD_CACHE_RESULT" | jq -r '.metrics.p95_latency_ms // "-"')
        if [[ "$cold_p50" != "null" && "$cold_p50" != "-" ]]; then
            cold_p50="${cold_p50}ms"
        fi
        if [[ "$cold_p95" != "null" && "$cold_p95" != "-" ]]; then
            cold_p95="${cold_p95}ms"
        fi
    fi
    
    # Extract warm cache data
    if [[ "$WARM_CACHE_RESULT" != "null" ]]; then
        if echo "$WARM_CACHE_RESULT" | jq -e '.passed == true' &>/dev/null; then
            warm_status="PASS"
        else
            warm_status="FAIL"
        fi
        warm_qps=$(echo "$WARM_CACHE_RESULT" | jq -r '.metrics.qps_actual // "-"')
        warm_p50=$(echo "$WARM_CACHE_RESULT" | jq -r '.metrics.p50_latency_ms // "-"')
        warm_p95=$(echo "$WARM_CACHE_RESULT" | jq -r '.metrics.p95_latency_ms // "-"')
        local warm_cache_hit=$(echo "$WARM_CACHE_RESULT" | jq -r '.metrics.cache_hit_ratio // "-"')
        if [[ "$warm_p50" != "null" && "$warm_p50" != "-" ]]; then
            warm_p50="${warm_p50}ms"
        fi
        if [[ "$warm_p95" != "null" && "$warm_p95" != "-" ]]; then
            warm_p95="${warm_p95}ms"
        fi
        if [[ "$warm_cache_hit" != "null" && "$warm_cache_hit" != "-" ]]; then
            warm_notes="${warm_cache_hit}% cache hit"
        fi
    fi
    
    # Extract saturation data
    if [[ "$SATURATION_RESULT" != "null" ]]; then
        if echo "$SATURATION_RESULT" | jq -e '.passed == true' &>/dev/null; then
            sat_status="PASS"
        else
            sat_status="FAIL"
        fi
        sat_qps=$(echo "$SATURATION_RESULT" | jq -r '.metrics.max_qps_sustained // "-"')
        sat_p50=$(echo "$SATURATION_RESULT" | jq -r '.metrics.latency_at_50pct_ms // "-"')
        sat_p95="-"
        if [[ "$sat_p50" != "null" && "$sat_p50" != "-" ]]; then
            sat_p50="${sat_p50}ms"
        fi
        sat_notes="Sustained at ${sat_qps} QPS"
    fi
    
    # Determine verdict
    local verdict
    if [[ $PHASES_FAILED -gt 0 ]]; then
        verdict="❌ **${PHASES_FAILED} PHASE(S) FAILED**"
    elif [[ $PHASES_PASSED -gt 0 ]]; then
        verdict="✅ **ALL PHASES PASSED**"
    else
        verdict="⚠️ **NO PHASES RUN**"
    fi
    
    cat << EOF
# DNS53 Benchmark Report

**Run ID**: $benchmark_id  
**Date**: $run_at  
**Target**: ${TARGET}:${PORT}  
**Mode**: $MODE  

## Summary

| Phase | Status | QPS | p50 | p95 | Notes |
|-------|--------|-----|-----|-----|-------|
| Cold Cache | $cold_status | $cold_qps | $cold_p50 | $cold_p95 | $cold_notes |
| Warm Cache | $warm_status | $warm_qps | $warm_p50 | $warm_p95 | $warm_notes |
| Saturation | $sat_status | $sat_qps | $sat_p50 | $sat_p95 | $sat_notes |

## Environment

- **Hostname**: $(hostname)
- **OS**: $(uname -s) $(uname -r)
- **Tool Version**: $SCRIPT_VERSION

## Configuration

- **Corpus**: $(basename "$CORPUS")
- **Duration**: ${DURATION}s per phase
- **Output Format**: $OUTPUT

## Verdict

$verdict

---
*Generated by dns53-benchmark.sh v${SCRIPT_VERSION}*
EOF
}

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

main() {
    # Parse command-line arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --mode)
                MODE="$2"
                shift 2
                ;;
            --target)
                TARGET="$2"
                shift 2
                ;;
            --port)
                PORT="$2"
                shift 2
                ;;
            --corpus)
                CORPUS="$2"
                shift 2
                ;;
            --duration)
                DURATION="$2"
                shift 2
                ;;
            --output)
                OUTPUT="$2"
                shift 2
                ;;
            --results-dir)
                RESULTS_DIR="$2"
                shift 2
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            --version|-v)
                show_version
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                echo "Use --help for usage information"
                exit $EXIT_CONFIG_ERROR
                ;;
        esac
    done

    log_section "DNS53 Benchmark Suite v${SCRIPT_VERSION}"

    # Step 1: Check prerequisites
    if ! check_prerequisites; then
        log_fail "Prerequisites not met"
        exit $EXIT_PREREQ_FAILED
    fi

    # Step 2: Validate configuration
    if ! validate_config; then
        log_fail "Configuration invalid"
        exit $EXIT_CONFIG_ERROR
    fi

    # Step 3: Run benchmark phases
    log_section "Running Benchmark Phases"

    case "$MODE" in
        cold)
            run_cold_cache_phase || true
            ;;
        warm)
            run_warm_cache_phase || true
            ;;
        saturation)
            run_saturation_phase || true
            ;;
        all)
            run_cold_cache_phase || true
            run_warm_cache_phase || true
            run_saturation_phase || true
            ;;
    esac

    # Step 4: Generate output
    log_section "Generating Output"

    local timestamp=$(date +%Y%m%d-%H%M%S)
    local json_file="${RESULTS_DIR}/benchmark-${timestamp}.json"
    local md_file="${RESULTS_DIR}/benchmark-${timestamp}.md"

    case "$OUTPUT" in
        json)
            generate_json_output > "$json_file"
            log_pass "JSON output: $json_file"
            ;;
        markdown)
            generate_markdown_output > "$md_file"
            log_pass "Markdown output: $md_file"
            ;;
        both)
            generate_json_output > "$json_file"
            generate_markdown_output > "$md_file"
            log_pass "JSON output: $json_file"
            log_pass "Markdown output: $md_file"
            ;;
    esac

    log_section "Benchmark Complete"
    
    # Summary
    log_info "Phases run: $PHASES_RUN | Passed: $PHASES_PASSED | Failed: $PHASES_FAILED"

    # Exit with appropriate code
    if [[ $PHASES_FAILED -gt 0 ]]; then
        log_fail "Performance regression detected!"
        exit $EXIT_PHASE_FAILED
    fi
    
    exit $EXIT_SUCCESS
}

# Run main with all arguments
main "$@"
