#!/usr/bin/env bash
#
# regression-gate-check.sh - PowerBlockade Regression Gate Evaluation
#
# Evaluates all regression gates for promotion decisions. Exit codes:
#   0 - All gates passed (promotion approved)
#   1 - One or more gates failed (promotion blocked)
#   2 - All mandatory gates passed, warnings present (allow with documentation)
#
# USAGE:
#   ./scripts/regression-gate-check.sh [OPTIONS]
#
# OPTIONS:
#   --benchmark-json FILE   Path to benchmark results JSON (optional)
#   --baseline FILE         Path to baseline event count file for parity checks
#   --docker-subnet CIDR    Docker subnet for internal traffic detection (default: 172.30.0.0/24)
#   --metrics-url URL       Prometheus metrics URL (default: http://localhost:8080/metrics)
#   --prometheus-url URL    Prometheus API URL (default: http://localhost:9090)
#   --database-url URL      PostgreSQL connection URL (or use DATABASE_URL env)
#   --output FORMAT         Output format: summary (default) or json
#   --help                  Show this help message
#
# GATES (per docs/performance/dns-cache-operations-runbook.md):
#
#   1. OBSERVABILITY GATES (mandatory - block on any failure)
#      - External query completeness >= 99.9%
#      - Internal container exclusion rate >= 99.9%
#
#   2. PARITY GATES (mandatory - block if delta > 10%)
#      - Event ingest parity (requires baseline file)
#      - No duplicate event IDs
#
#   3. PERFORMANCE GATES
#      - No high latency Prometheus alerts firing
#      - Cache hit rate >= 50% (block if < 20%)
#
# CONTRACT: This script is idempotent and safe to re-run at any time.
#
# Reference: docs/performance/dns-cache-operations-runbook.md
# =============================================================================

set -uo pipefail

# =============================================================================
# CONFIGURATION
# =============================================================================

readonly SCRIPT_NAME="regression-gate-check.sh"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Gate order for consistent output
GATE_ORDER="external_completeness internal_exclusion event_parity no_duplicates schema_integrity no_latency_alerts cache_hit_rate benchmark_latency benchmark_qps"

# Default settings
DOCKER_SUBNET="${DOCKER_SUBNET:-172.30.0.0/24}"
METRICS_URL="${METRICS_URL:-http://localhost:8080/metrics}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
DATABASE_URL="${DATABASE_URL:-}"
BENCHMARK_JSON="${BENCHMARK_JSON:-}"
BASELINE_FILE="${BASELINE_FILE:-}"
OUTPUT_FORMAT="${OUTPUT_FORMAT:-summary}"

# Gate counters
GATES_PASSED=0
GATES_WARNED=0
GATES_FAILED=0

# Temp files for results (bash 3.x compatible)
RESULTS_FILE=""
MESSAGES_FILE=""

# Colors (only for terminal output)
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    BOLD=''
    NC=''
fi

# =============================================================================
# CLEANUP
# =============================================================================

cleanup() {
    rm -f "$RESULTS_FILE" "$MESSAGES_FILE" 2>/dev/null || true
}

trap cleanup EXIT

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

log_info()  { echo -e "${BLUE}[INFO]${NC} $*" >&2; }
log_pass()  { echo -e "${GREEN}[PASS]${NC} $*" >&2; }
log_fail()  { echo -e "${RED}[FAIL]${NC} $*" >&2; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
log_block() { echo -e "${RED}[BLOCK]${NC} $*" >&2; }

log_section() {
    echo "" >&2
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}" >&2
    echo -e "${CYAN} $*${NC}" >&2
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}" >&2
}

get_result() {
    local gate="$1"
    grep "^${gate}=" "$RESULTS_FILE" 2>/dev/null | cut -d= -f2- || echo "unknown"
}

set_result() {
    local gate="$1"
    local status="$2"
    local message="${3:-}"
    
    grep -v "^${gate}=" "$RESULTS_FILE" 2>/dev/null > "${RESULTS_FILE}.tmp" || true
    echo "${gate}=${status}" >> "${RESULTS_FILE}.tmp"
    mv "${RESULTS_FILE}.tmp" "$RESULTS_FILE"
    
    grep -v "^${gate}=" "$MESSAGES_FILE" 2>/dev/null > "${MESSAGES_FILE}.tmp" || true
    echo "${gate}=${message}" >> "${MESSAGES_FILE}.tmp"
    mv "${MESSAGES_FILE}.tmp" "$MESSAGES_FILE"
}

get_message() {
    local gate="$1"
    grep "^${gate}=" "$MESSAGES_FILE" 2>/dev/null | cut -d= -f2- || echo ""
}

record_gate() {
    local gate="$1"
    local status="$2"
    local message="${3:-}"
    
    set_result "$gate" "$status" "$message"
    
    case "$status" in
        passed) 
            log_pass "$gate: $message"
            ((GATES_PASSED++)) 
            ;;
        warned) 
            log_warn "$gate: $message"
            ((GATES_WARNED++)) 
            ;;
        failed) 
            log_fail "$gate: $message"
            ((GATES_FAILED++)) 
            ;;
    esac
}

command_exists() {
    command -v "$1" &>/dev/null
}

compare_float() {
    local left="$1"
    local op="$2"
    local right="$3"
    
    if ! command_exists bc; then
        awk -v l="$left" -v r="$right" -v op="$op" 'BEGIN {
            if (op == ">=") exit !(l >= r)
            if (op == "<=") exit !(l <= r)
            if (op == ">")  exit !(l > r)
            if (op == "<")  exit !(l < r)
            if (op == "==") exit !(l == r)
            exit 1
        }'
        return $?
    fi
    
    local result
    result=$(echo "$left $op $right" | bc -l 2>/dev/null)
    [[ "$result" == "1" ]]
}

run_sql() {
    local query="$1"
    
    if [[ -n "$DATABASE_URL" ]]; then
        psql "$DATABASE_URL" -t -c "$query" 2>/dev/null | tr -d ' \n'
    else
        docker compose exec -T postgres psql -U powerblockade -t -c "$query" 2>/dev/null | tr -d ' \n'
    fi
}

run_sql_with_stderr() {
    local query="$1"
    
    if [[ -n "$DATABASE_URL" ]]; then
        psql "$DATABASE_URL" -t -c "$query" 2>&1 | tr -d ' \n'
    else
        docker compose exec -T postgres psql -U powerblockade -t -c "$query" 2>&1 | tr -d ' \n'
    fi
}

fetch_url() {
    local url="$1"
    local timeout="${2:-10}"
    
    curl -sf --max-time "$timeout" "$url" 2>/dev/null
}

# =============================================================================
# GATE FUNCTIONS
# =============================================================================

gate_external_completeness() {
    log_section "Gate 1: External Query Completeness"
    
    local query="
        SELECT 
            COALESCE(
                COUNT(*) FILTER (WHERE NOT client_ip <<= '${DOCKER_SUBNET}')::float / 
                NULLIF(COUNT(*), 0) * 100,
                0
            )
        FROM dns_query_events 
        WHERE ts > now() - interval '1 hour'
    "
    
    local completeness
    completeness=$(run_sql "$query")
    
    if [[ -z "$completeness" ]]; then
        record_gate "external_completeness" "failed" "Could not query database"
        return 1
    fi
    
    local total_count
    total_count=$(run_sql "SELECT COUNT(*) FROM dns_query_events WHERE ts > now() - interval '1 hour'")
    
    if [[ -z "$total_count" || "$total_count" == "0" ]]; then
        record_gate "external_completeness" "warned" "No events in last hour"
        return 0
    fi
    
    if compare_float "$completeness" ">=" 99.9; then
        record_gate "external_completeness" "passed" "${completeness}% >= 99.9%"
        return 0
    else
        record_gate "external_completeness" "failed" "${completeness}% < 99.9% (BLOCK)"
        return 1
    fi
}

gate_internal_exclusion() {
    log_section "Gate 2: Internal Container Exclusion"
    
    local query="
        SELECT COUNT(*) 
        FROM dns_query_events 
        WHERE ts > now() - interval '1 hour'
          AND client_ip <<= '${DOCKER_SUBNET}'
          AND is_internal = false
    "
    
    local misclassified
    misclassified=$(run_sql "$query")
    
    if [[ -z "$misclassified" ]]; then
        record_gate "internal_exclusion" "failed" "Could not query database"
        return 1
    fi
    
    if [[ "$misclassified" -eq 0 ]]; then
        record_gate "internal_exclusion" "passed" "0 internal queries misflagged"
        return 0
    else
        record_gate "internal_exclusion" "failed" "$misclassified internal queries in display (BLOCK)"
        return 1
    fi
}

gate_event_parity() {
    log_section "Gate 3: Event Ingest Parity"
    
    if [[ -z "$BASELINE_FILE" || ! -f "$BASELINE_FILE" ]]; then
        record_gate "event_parity" "warned" "No baseline file (set --baseline)"
        return 0
    fi
    
    local baseline_count
    baseline_count=$(cat "$BASELINE_FILE" 2>/dev/null | tr -d ' \n')
    
    if [[ -z "$baseline_count" || ! "$baseline_count" =~ ^[0-9]+$ ]]; then
        record_gate "event_parity" "failed" "Invalid baseline file"
        return 1
    fi
    
    local current_count
    current_count=$(run_sql "SELECT COUNT(*) FROM dns_query_events WHERE ts > now() - interval '1 hour'")
    
    if [[ -z "$current_count" || "$current_count" == "0" ]]; then
        record_gate "event_parity" "warned" "No events in last hour"
        return 0
    fi
    
    local parity_ratio
    if command_exists bc; then
        parity_ratio=$(echo "scale=4; $current_count / $baseline_count" | bc 2>/dev/null)
    else
        parity_ratio=$(awk "BEGIN {printf \"%.4f\", $current_count / $baseline_count}")
    fi
    
    if compare_float "$parity_ratio" ">=" 0.95 && compare_float "$parity_ratio" "<=" 1.05; then
        record_gate "event_parity" "passed" "ratio=${parity_ratio}"
        return 0
    elif compare_float "$parity_ratio" "<" 0.90 || compare_float "$parity_ratio" ">" 1.10; then
        record_gate "event_parity" "failed" "ratio=${parity_ratio} outside 0.90-1.10 (BLOCK)"
        return 1
    else
        record_gate "event_parity" "warned" "ratio=${parity_ratio} outside 0.95-1.05"
        return 0
    fi
}

gate_no_duplicates() {
    log_section "Gate 4: No Duplicate Event IDs"
    
    local query="
        SELECT COUNT(*) - COUNT(DISTINCT id)
        FROM dns_query_events 
        WHERE ts > now() - interval '1 hour'
    "
    
    local duplicates
    duplicates=$(run_sql "$query")
    
    if [[ -z "$duplicates" ]]; then
        record_gate "no_duplicates" "failed" "Could not query database"
        return 1
    fi
    
    if [[ "$duplicates" -eq 0 ]]; then
        record_gate "no_duplicates" "passed" "0 duplicate event IDs"
        return 0
    else
        record_gate "no_duplicates" "failed" "$duplicates duplicate event IDs (BLOCK)"
        return 1
    fi
}

gate_schema_integrity() {
    log_section "Gate 5: Schema Integrity"
    
    local result
    result=$(run_sql_with_stderr "SELECT COUNT(*) FROM dns_query_events WHERE ts > now() - interval '1 hour' LIMIT 1")
    
    if [[ "$result" =~ "does not exist" || "$result" =~ "column" ]]; then
        record_gate "schema_integrity" "failed" "Schema error"
        return 1
    fi
    
    local column_check
    column_check=$(run_sql_with_stderr "
        SELECT COUNT(*) FROM dns_query_events 
        WHERE ts > now() - interval '1 hour'
          AND client_ip IS NOT NULL
          AND latency_ms IS NOT NULL
          AND blocked IS NOT NULL
    ")
    
    if [[ "$column_check" =~ "does not exist" ]]; then
        record_gate "schema_integrity" "failed" "Missing required columns"
        return 1
    fi
    
    record_gate "schema_integrity" "passed" "All required columns accessible"
    return 0
}

gate_no_latency_alerts() {
    log_section "Gate 6: No High Latency Alerts"
    
    local alerts_json
    alerts_json=$(fetch_url "${PROMETHEUS_URL}/api/v1/alerts" 10)
    
    if [[ -z "$alerts_json" ]]; then
        record_gate "no_latency_alerts" "warned" "Prometheus not reachable"
        return 0
    fi
    
    if command_exists jq; then
        local firing_alerts
        firing_alerts=$(echo "$alerts_json" | jq -r '
            .data.alerts[] | 
            select(.labels.alertname == "HighQueryLatency" and .state == "firing") | 
            .labels.alertname
        ' 2>/dev/null | head -1)
        
        if [[ -n "$firing_alerts" ]]; then
            record_gate "no_latency_alerts" "failed" "HighQueryLatency alert firing (BLOCK)"
            return 1
        fi
        
        local alert_count
        alert_count=$(echo "$alerts_json" | jq -r '[.data.alerts[] | select(.state == "firing")] | length' 2>/dev/null)
        
        if [[ "$alert_count" -gt 0 ]]; then
            record_gate "no_latency_alerts" "warned" "$alert_count non-latency alerts firing"
            return 0
        fi
    fi
    
    record_gate "no_latency_alerts" "passed" "No alerts firing"
    return 0
}

gate_cache_hit_rate() {
    log_section "Gate 7: Cache Hit Rate"
    
    local metrics
    metrics=$(fetch_url "$METRICS_URL" 10)
    
    local cache_hit
    cache_hit=$(echo "$metrics" | grep "^powerblockade_cache_hit_rate " | awk '{print $2}' | head -1)
    
    if [[ -z "$cache_hit" ]]; then
        local hits total
        hits=$(run_sql "
            SELECT COUNT(*) FROM dns_query_events 
            WHERE ts > now() - interval '1 hour' 
              AND latency_ms < 5 
              AND blocked = false
        ")
        total=$(run_sql "
            SELECT COUNT(*) FROM dns_query_events 
            WHERE ts > now() - interval '1 hour' 
              AND blocked = false
        ")
        
        if [[ -n "$total" && "$total" != "0" ]]; then
            if command_exists bc; then
                cache_hit=$(echo "scale=2; $hits * 100 / $total" | bc 2>/dev/null)
            else
                cache_hit=$(awk "BEGIN {printf \"%.2f\", $hits * 100 / $total}")
            fi
        fi
    fi
    
    if [[ -z "$cache_hit" ]]; then
        record_gate "cache_hit_rate" "warned" "Could not determine cache hit rate"
        return 0
    fi
    
    if compare_float "$cache_hit" ">=" 50; then
        record_gate "cache_hit_rate" "passed" "${cache_hit}% >= 50%"
        return 0
    elif compare_float "$cache_hit" "<" 20; then
        record_gate "cache_hit_rate" "failed" "${cache_hit}% < 20% (BLOCK)"
        return 1
    else
        record_gate "cache_hit_rate" "warned" "${cache_hit}% < 50%"
        return 0
    fi
}

gate_benchmark_latency() {
    log_section "Gate 8: Benchmark Latency Gates"
    
    if [[ -z "$BENCHMARK_JSON" || ! -f "$BENCHMARK_JSON" ]]; then
        record_gate "benchmark_latency" "warned" "No benchmark JSON (set --benchmark-json)"
        return 0
    fi
    
    if ! command_exists jq; then
        record_gate "benchmark_latency" "warned" "jq required"
        return 0
    fi
    
    local failed=0
    local messages=""
    
    local cold_p50
    cold_p50=$(jq -r '.phases.cold_cache.metrics.p50_latency_ms // empty' "$BENCHMARK_JSON" 2>/dev/null)
    if [[ -n "$cold_p50" ]] && compare_float "$cold_p50" ">" 25; then
        messages+="Cold p50=${cold_p50}ms > 25ms. "
        failed=1
    fi
    
    local warm_p50
    warm_p50=$(jq -r '.phases.warm_cache.metrics.p50_latency_ms // empty' "$BENCHMARK_JSON" 2>/dev/null)
    if [[ -n "$warm_p50" ]] && compare_float "$warm_p50" ">" 6.25; then
        messages+="Warm p50=${warm_p50}ms > 6.25ms. "
        failed=1
    fi
    
    local warm_p95
    warm_p95=$(jq -r '.phases.warm_cache.metrics.p95_latency_ms // empty' "$BENCHMARK_JSON" 2>/dev/null)
    if [[ -n "$warm_p95" ]] && compare_float "$warm_p95" ">" 25; then
        messages+="Warm p95=${warm_p95}ms > 25ms. "
        failed=1
    fi
    
    if [[ $failed -eq 1 ]]; then
        record_gate "benchmark_latency" "failed" "$messages"
        return 1
    else
        record_gate "benchmark_latency" "passed" "All latency thresholds met"
        return 0
    fi
}

gate_benchmark_qps() {
    log_section "Gate 9: Benchmark QPS Gates"
    
    if [[ -z "$BENCHMARK_JSON" || ! -f "$BENCHMARK_JSON" ]]; then
        record_gate "benchmark_qps" "warned" "No benchmark JSON"
        return 0
    fi
    
    if ! command_exists jq; then
        record_gate "benchmark_qps" "warned" "jq required"
        return 0
    fi
    
    local failed=0
    local messages=""
    
    local warm_qps
    warm_qps=$(jq -r '.phases.warm_cache.metrics.qps_actual // empty' "$BENCHMARK_JSON" 2>/dev/null)
    if [[ -n "$warm_qps" ]] && compare_float "$warm_qps" "<" 3200; then
        messages+="Warm QPS=${warm_qps} < 3200. "
        failed=1
    fi
    
    local sat_qps
    sat_qps=$(jq -r '.phases.saturation.metrics.max_qps_sustained // empty' "$BENCHMARK_JSON" 2>/dev/null)
    if [[ -n "$sat_qps" ]] && compare_float "$sat_qps" "<" 4000; then
        messages+="Saturation QPS=${sat_qps} < 4000. "
        failed=1
    fi
    
    if [[ $failed -eq 1 ]]; then
        record_gate "benchmark_qps" "failed" "$messages"
        return 1
    else
        record_gate "benchmark_qps" "passed" "All QPS thresholds met"
        return 0
    fi
}

# =============================================================================
# OUTPUT FUNCTIONS
# =============================================================================

output_json() {
    local overall="passed"
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    if [[ $GATES_FAILED -gt 0 ]]; then
        overall="failed"
    elif [[ $GATES_WARNED -gt 0 ]]; then
        overall="warned"
    fi
    
    local gates_json=""
    for gate in $GATE_ORDER; do
        local status
        status=$(get_result "$gate")
        local message
        message=$(get_message "$gate")
        message="${message//\"/\\\"}"
        
        if [[ -n "$gates_json" ]]; then
            gates_json+=","
        fi
        gates_json+="\"$gate\":{\"status\":\"$status\",\"message\":\"$message\"}"
    done
    
    local total=0
    for _ in $GATE_ORDER; do total=$((total + 1)); done
    
    cat <<EOF
{
  "version": "1.0.0",
  "script": "$SCRIPT_NAME",
  "timestamp": "$timestamp",
  "overall": "$overall",
  "summary": {
    "passed": $GATES_PASSED,
    "warned": $GATES_WARNED,
    "failed": $GATES_FAILED,
    "total": $total
  },
  "gates": {$gates_json}
}
EOF
}

output_summary() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "                 REGRESSION GATE SUMMARY                        "
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    
    for gate in $GATE_ORDER; do
        local status
        status=$(get_result "$gate")
        local message
        message=$(get_message "$gate")
        
        case "$status" in
            passed)
                echo -e "  ${GREEN}✓${NC} $gate"
                ;;
            warned)
                echo -e "  ${YELLOW}!${NC} $gate - $message"
                ;;
            failed)
                echo -e "  ${RED}✗${NC} $gate - $message"
                ;;
            unknown)
                ;;
        esac
    done
    
    echo ""
    echo "───────────────────────────────────────────────────────────────"
    echo -e "  ${GREEN}Passed:${NC}  $GATES_PASSED"
    echo -e "  ${YELLOW}Warned:${NC}  $GATES_WARNED"
    echo -e "  ${RED}Failed:${NC}  $GATES_FAILED"
    echo "───────────────────────────────────────────────────────────────"
    echo ""
    
    if [[ $GATES_FAILED -gt 0 ]]; then
        echo -e "${RED}╔═══════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║              PROMOTION BLOCKED - GATES FAILED                 ║${NC}"
        echo -e "${RED}║                                                               ║${NC}"
        echo -e "${RED}║  Fix failed gates before proceeding.                          ║${NC}"
        echo -e "${RED}║  See: docs/performance/dns-cache-operations-runbook.md        ║${NC}"
        echo -e "${RED}╚═══════════════════════════════════════════════════════════════╝${NC}"
    elif [[ $GATES_WARNED -gt 0 ]]; then
        echo -e "${YELLOW}╔═══════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${YELLOW}║         PROMOTION ALLOWED WITH WARNINGS                       ║${NC}"
        echo -e "${YELLOW}║                                                               ║${NC}"
        echo -e "${YELLOW}║  Document warnings in release notes before proceeding.        ║${NC}"
        echo -e "${YELLOW}╚═══════════════════════════════════════════════════════════════╝${NC}"
    else
        echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║              ALL GATES PASSED - PROMOTION APPROVED            ║${NC}"
        echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    fi
}

show_help() {
    cat <<EOF
Usage: $SCRIPT_NAME [OPTIONS]

PowerBlockade Regression Gate Evaluation

Evaluates all regression gates for promotion decisions per the runbook at:
  docs/performance/dns-cache-operations-runbook.md

Options:
  --benchmark-json FILE   Path to benchmark results JSON (optional)
  --baseline FILE         Path to baseline event count file for parity checks
  --docker-subnet CIDR    Docker subnet (default: 172.30.0.0/24)
  --metrics-url URL       Prometheus metrics URL (default: http://localhost:8080/metrics)
  --prometheus-url URL    Prometheus API URL (default: http://localhost:9090)
  --database-url URL      PostgreSQL connection URL (or use DATABASE_URL env)
  --output FORMAT         Output format: summary (default) or json
  --help                  Show this help message

Exit Codes:
  0 - All gates passed (promotion approved)
  1 - One or more gates failed (promotion blocked)
  2 - All mandatory gates passed, warnings present (allow with documentation)

Gates:
  OBSERVABILITY (mandatory - block on any failure):
    1. external_completeness - External query completeness >= 99.9%
    2. internal_exclusion    - Internal container exclusion rate >= 99.9%

  PARITY (mandatory - block if delta > 10%):
    3. event_parity          - Event ingest parity (requires --baseline)
    4. no_duplicates         - No duplicate event IDs
    5. schema_integrity      - Schema integrity preserved

  PERFORMANCE:
    6. no_latency_alerts     - No high latency Prometheus alerts firing
    7. cache_hit_rate        - Cache hit rate >= 50% (block if < 20%)

  BENCHMARK (requires --benchmark-json):
    8. benchmark_latency     - Latency thresholds (cold p50 < 25ms, warm p50 < 6.25ms)
    9. benchmark_qps         - QPS thresholds (warm > 3200, saturation > 4000)

Examples:
  # Basic run with live system checks
  $SCRIPT_NAME

  # With benchmark results and baseline
  $SCRIPT_NAME --benchmark-json results.json --baseline baseline-event-count.txt

  # JSON output for CI integration
  $SCRIPT_NAME --output json

  # Custom database URL
  $SCRIPT_NAME --database-url "postgresql://user:pass@host/db"

Reference:
  docs/performance/dns-cache-operations-runbook.md
EOF
}

# =============================================================================
# CLI ARGUMENT PARSING
# =============================================================================

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --benchmark-json)
                BENCHMARK_JSON="$2"
                shift 2
                ;;
            --baseline)
                BASELINE_FILE="$2"
                shift 2
                ;;
            --docker-subnet)
                DOCKER_SUBNET="$2"
                shift 2
                ;;
            --metrics-url)
                METRICS_URL="$2"
                shift 2
                ;;
            --prometheus-url)
                PROMETHEUS_URL="$2"
                shift 2
                ;;
            --database-url)
                DATABASE_URL="$2"
                shift 2
                ;;
            --output)
                OUTPUT_FORMAT="$2"
                shift 2
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_fail "Unknown option: $1"
                echo "Run '$SCRIPT_NAME --help' for usage information"
                exit 2
                ;;
        esac
    done
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    parse_args "$@"
    
    cd "$PROJECT_ROOT"
    
    RESULTS_FILE=$(mktemp)
    MESSAGES_FILE=$(mktemp)
    
    for gate in $GATE_ORDER; do
        echo "${gate}=unknown" >> "$RESULTS_FILE"
        echo "${gate}=" >> "$MESSAGES_FILE"
    done
    
    echo "" >&2
    echo "╔═══════════════════════════════════════════════════════════════╗" >&2
    echo "║        PowerBlockade Regression Gate Check                    ║" >&2
    echo "╚═══════════════════════════════════════════════════════════════╝" >&2
    echo "" >&2
    log_info "Time: $(date -Iseconds)"
    log_info "Docker subnet: $DOCKER_SUBNET"
    
    gate_external_completeness || true
    gate_internal_exclusion || true
    gate_event_parity || true
    gate_no_duplicates || true
    gate_schema_integrity || true
    gate_no_latency_alerts || true
    gate_cache_hit_rate || true
    gate_benchmark_latency || true
    gate_benchmark_qps || true
    
    if [[ "$OUTPUT_FORMAT" == "json" ]]; then
        output_json
    else
        output_summary
    fi
    
    if [[ $GATES_FAILED -gt 0 ]]; then
        exit 1
    elif [[ $GATES_WARNED -gt 0 ]]; then
        exit 2
    else
        exit 0
    fi
}

main "$@"
