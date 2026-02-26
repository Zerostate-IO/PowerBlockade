#!/usr/bin/env bash
#
# run-local-cache-gates.sh - Deterministic local validation gate runner
#
# Executes all validation gates in fixed order and produces machine-readable output.
# Exits non-zero if any gate fails.
#
# USAGE:
#   ./scripts/benchmarks/run-local-cache-gates.sh [--output json|summary] [--skip smoke]
#
# EXIT CODES:
#   0 - All gates passed
#   1 - One or more gates failed
#   2 - Prerequisites not met
#
# OUTPUT:
#   By default outputs JSON summary to stdout. Use --output summary for human-readable.
#
# GATES (in order):
#   1. lint        - ruff check
#   2. format      - ruff format --check
#   3. type        - pyright type check
#   4. unit        - pytest unit tests
#   5. integration - pytest integration tests
#   6. go-dnstap   - Go tests for dnstap-processor
#   7. go-sync     - Go tests for sync-agent (if present)
#   8. build       - docker compose build
#   9. smoke       - health check and DNS query verification
#
# CONTRACT: This script is idempotent and safe to re-run at any time.
#
# =============================================================================

set -uo pipefail

# =============================================================================
# CONFIGURATION
# =============================================================================

readonly SCRIPT_NAME="run-local-cache-gates.sh"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly ADMIN_UI_DIR="${PROJECT_ROOT}/admin-ui"
readonly DNSTAP_DIR="${PROJECT_ROOT}/dnstap-processor"
readonly SYNC_AGENT_DIR="${PROJECT_ROOT}/sync-agent"

# Gate order
GATE_ORDER="lint format type unit integration go-dnstap go-sync build smoke"

# Default settings
OUTPUT_FORMAT="${OUTPUT_FORMAT:-json}"
SKIP_GATES="${SKIP_GATES:-}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-30}"

# Temp files for results (compatible with bash 3.x)
RESULTS_FILE=""
MESSAGES_FILE=""

# Colors (only for terminal output)
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
# CLEANUP
# =============================================================================

cleanup() {
    rm -f "$RESULTS_FILE" "$MESSAGES_FILE" 2>/dev/null || true
}

trap cleanup EXIT

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

log_info() { echo -e "${BLUE}[INFO]${NC} $*" >&2; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $*" >&2; }
log_fail() { echo -e "${RED}[FAIL]${NC} $*" >&2; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
log_section() { echo -e "\n${CYAN}═══════════════════════════════════════════════════════════${NC}" >&2
                echo -e "${CYAN} $*${NC}" >&2
                echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}\n" >&2; }

# Get result for a gate
get_result() {
    local gate="$1"
    grep "^${gate}=" "$RESULTS_FILE" 2>/dev/null | cut -d= -f2- || echo "unknown"
}

# Set result for a gate
set_result() {
    local gate="$1"
    local status="$2"
    local message="${3:-}"
    

    grep -v "^${gate}=" "$RESULTS_FILE" 2>/dev/null > "${RESULTS_FILE}.tmp" || true
    echo "${gate}=${status}" >> "${RESULTS_FILE}.tmp"
    mv "${RESULTS_FILE}.tmp" "$RESULTS_FILE"
    
    # Store message
    grep -v "^${gate}=" "$MESSAGES_FILE" 2>/dev/null > "${MESSAGES_FILE}.tmp" || true
    echo "${gate}=${message}" >> "${MESSAGES_FILE}.tmp"
    mv "${MESSAGES_FILE}.tmp" "$MESSAGES_FILE"
}

# Get message for a gate
get_message() {
    local gate="$1"
    grep "^${gate}=" "$MESSAGES_FILE" 2>/dev/null | cut -d= -f2- || echo ""
}

record_gate() {
    local gate="$1"
    local status="$2"
    local message="${3:-}"
    
    set_result "$gate" "$status" "$message"
    
    if [[ "$status" == "passed" ]]; then
        log_pass "Gate: $gate"
    else
        log_fail "Gate: $gate - $message"
    fi
}

should_skip() {
    local gate="$1"
    [[ "$SKIP_GATES" == *"$gate"* ]]
}

check_prerequisites() {
    local missing=0
    
    if ! command -v uv &>/dev/null; then
        log_fail "Missing: uv (Python toolchain manager)"
        missing=1
    fi
    
    if ! command -v docker &>/dev/null; then
        log_fail "Missing: docker"
        missing=1
    fi
    
    if ! docker compose version &>/dev/null; then
        log_fail "Missing: docker compose"
        missing=1
    fi
    
    if ! command -v jq &>/dev/null; then
        log_fail "Missing: jq"
        missing=1
    fi
    
    return $missing
}

# =============================================================================
# GATE FUNCTIONS
# =============================================================================

gate_lint() {
    log_section "Gate 1: Lint (ruff check)"
    
    if should_skip "lint"; then
        log_warn "Skipping lint gate"
        record_gate "lint" "passed" "skipped"
        return 0
    fi
    
    cd "$ADMIN_UI_DIR"
    
    local output
    if output=$(uv run ruff check . 2>&1); then
        record_gate "lint" "passed" "No linting errors"
        return 0
    else
        record_gate "lint" "failed" "$output"
        return 1
    fi
}

gate_format() {
    log_section "Gate 2: Format Check (ruff format --check)"
    
    if should_skip "format"; then
        log_warn "Skipping format gate"
        record_gate "format" "passed" "skipped"
        return 0
    fi
    
    cd "$ADMIN_UI_DIR"
    
    local output
    if output=$(uv run ruff format --check . 2>&1); then
        record_gate "format" "passed" "Formatting correct"
        return 0
    else
        record_gate "format" "failed" "Run 'ruff format .' to fix"
        return 1
    fi
}

gate_type() {
    log_section "Gate 3: Type Check (pyright)"
    
    if should_skip "type"; then
        log_warn "Skipping type gate"
        record_gate "type" "passed" "skipped"
        return 0
    fi
    
    cd "$ADMIN_UI_DIR"
    
    local output exit_code
    set +e
    output=$(uv run pyright 2>&1)
    exit_code=$?
    set -e
    
    if [[ $exit_code -eq 0 ]]; then
        record_gate "type" "passed" "No type errors"
        return 0
    else
        if echo "$output" | grep -qE "error:|Error:"; then
            record_gate "type" "failed" "Type errors found"
            return 1
        else
            record_gate "type" "passed" "Type check completed with warnings only"
            return 0
        fi
    fi
}

gate_unit() {
    log_section "Gate 4: Unit Tests"
    
    if should_skip "unit"; then
        log_warn "Skipping unit tests gate"
        record_gate "unit" "passed" "skipped"
        return 0
    fi
    
    cd "$ADMIN_UI_DIR"
    
    local output exit_code
    set +e
    output=$(uv run pytest tests/unit/ -v --tb=short 2>&1)
    exit_code=$?
    set -e
    
    if [[ $exit_code -eq 0 ]]; then
        local summary
        summary=$(echo "$output" | grep -E "passed|failed" | tail -1)
        record_gate "unit" "passed" "$summary"
        return 0
    else
        record_gate "unit" "failed" "Unit tests failed (exit: $exit_code)"
        return 1
    fi
}

gate_integration() {
    log_section "Gate 5: Integration Tests"
    
    if should_skip "integration"; then
        log_warn "Skipping integration tests gate"
        record_gate "integration" "passed" "skipped"
        return 0
    fi
    
    cd "$ADMIN_UI_DIR"
    
    if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
        log_warn "TEST_DATABASE_URL not set, integration tests may fail"
    fi
    
    local output exit_code
    set +e
    output=$(uv run pytest tests/integration/ -v --tb=short 2>&1)
    exit_code=$?
    set -e
    
    if [[ $exit_code -eq 0 ]]; then
        local summary
        summary=$(echo "$output" | grep -E "passed|failed" | tail -1)
        record_gate "integration" "passed" "$summary"
        return 0
    else
        record_gate "integration" "failed" "Integration tests failed (exit: $exit_code)"
        return 1
    fi
}

gate_go_dnstap() {
    log_section "Gate 6: Go Tests (dnstap-processor)"
    
    if should_skip "go-dnstap"; then
        log_warn "Skipping dnstap-processor tests gate"
        record_gate "go-dnstap" "passed" "skipped"
        return 0
    fi
    
    if [[ ! -d "$DNSTAP_DIR" ]]; then
        log_warn "dnstap-processor directory not found, skipping"
        record_gate "go-dnstap" "passed" "directory not found"
        return 0
    fi
    
    if [[ ! -f "$DNSTAP_DIR/go.mod" ]]; then
        log_warn "dnstap-processor/go.mod not found, skipping"
        record_gate "go-dnstap" "passed" "go.mod not found"
        return 0
    fi
    
    cd "$DNSTAP_DIR"
    
    local output exit_code
    set +e
    output=$(go test ./... -v 2>&1)
    exit_code=$?
    set -e
    
    if [[ $exit_code -eq 0 ]]; then
        local summary
        summary=$(echo "$output" | grep -E "PASS|FAIL" | tail -5 | tr '\n' ' ')
        record_gate "go-dnstap" "passed" "$summary"
        return 0
    else
        record_gate "go-dnstap" "failed" "Go tests failed (exit: $exit_code)"
        return 1
    fi
}

gate_go_sync() {
    log_section "Gate 7: Go Tests (sync-agent)"
    
    if should_skip "go-sync"; then
        log_warn "Skipping sync-agent tests gate"
        record_gate "go-sync" "passed" "skipped"
        return 0
    fi
    
    if [[ ! -d "$SYNC_AGENT_DIR" ]]; then
        log_warn "sync-agent directory not found, skipping"
        record_gate "go-sync" "passed" "directory not found"
        return 0
    fi
    
    if [[ ! -f "$SYNC_AGENT_DIR/go.mod" ]]; then
        log_warn "sync-agent/go.mod not found, skipping"
        record_gate "go-sync" "passed" "go.mod not found"
        return 0
    fi
    
    cd "$SYNC_AGENT_DIR"
    
    local output exit_code
    set +e
    output=$(go test ./... -v 2>&1)
    exit_code=$?
    set -e
    
    if [[ $exit_code -eq 0 ]]; then
        local summary
        summary=$(echo "$output" | grep -E "PASS|FAIL" | tail -5 | tr '\n' ' ')
        record_gate "go-sync" "passed" "$summary"
        return 0
    else
        record_gate "go-sync" "failed" "Go tests failed (exit: $exit_code)"
        return 1
    fi
}

gate_build() {
    log_section "Gate 8: Docker Compose Build"
    
    if should_skip "build"; then
        log_warn "Skipping build gate"
        record_gate "build" "passed" "skipped"
        return 0
    fi
    
    cd "$PROJECT_ROOT"
    
    local output exit_code
    set +e
    output=$(docker compose build --quiet 2>&1)
    exit_code=$?
    set -e
    
    if [[ $exit_code -eq 0 ]]; then
        record_gate "build" "passed" "All services built successfully"
        return 0
    else
        record_gate "build" "failed" "Docker build failed (exit: $exit_code)"
        return 1
    fi
}

gate_smoke() {
    log_section "Gate 9: Runtime Smoke Tests"
    
    if should_skip "smoke"; then
        log_warn "Skipping smoke gate"
        record_gate "smoke" "passed" "skipped"
        return 0
    fi
    
    cd "$PROJECT_ROOT"
    
    local smoke_errors=0
    local smoke_messages=""
    
    if ! docker compose ps 2>/dev/null | grep -q "Up"; then
        log_info "Starting stack for smoke tests..."
        docker compose up -d --wait --timeout 60 2>/dev/null || {
            record_gate "smoke" "failed" "Could not start stack"
            return 1
        }
    fi
    
    log_info "Checking Admin UI health..."
    local health_response
    if health_response=$(curl -sf --max-time "$SMOKE_TIMEOUT" "http://localhost:8080/health" 2>/dev/null); then
        if echo "$health_response" | grep -qE '"ok"\s*:\s*true|"status"\s*:\s*"ok"'; then
            smoke_messages="${smoke_messages}Admin UI: healthy, "
            log_info "Admin UI: healthy"
        else
            smoke_errors=$((smoke_errors + 1))
            smoke_messages="${smoke_messages}Admin UI: unhealthy, "
        fi
    else
        smoke_errors=$((smoke_errors + 1))
        smoke_messages="${smoke_messages}Admin UI: not responding, "
    fi
    
    log_info "Testing DNS resolution..."
    local dns_result
    if dns_result=$(dig +short +time=5 +tries=1 @127.0.0.1 google.com A 2>/dev/null | head -1); then
        if [[ -n "$dns_result" && "$dns_result" != "0.0.0.0" ]]; then
            smoke_messages="${smoke_messages}DNS: resolving (${dns_result})"
            log_info "DNS: resolving (${dns_result})"
        else
            smoke_errors=$((smoke_errors + 1))
            smoke_messages="${smoke_messages}DNS: blocked or empty result"
        fi
    else
        smoke_errors=$((smoke_errors + 1))
        smoke_messages="${smoke_messages}DNS: query failed"
    fi
    
    if [[ $smoke_errors -eq 0 ]]; then
        record_gate "smoke" "passed" "$smoke_messages"
        return 0
    else
        record_gate "smoke" "failed" "$smoke_messages"
        return 1
    fi
}

# =============================================================================
# OUTPUT FUNCTIONS
# =============================================================================

output_json() {
    local overall="passed"
    local failed_count=0
    local passed_count=0
    local skipped_count=0
    
    for gate in $GATE_ORDER; do
        local status
        status=$(get_result "$gate")
        local message
        message=$(get_message "$gate")
        
        case "$status" in
            passed)
                if [[ "$message" == *"skipped"* ]]; then
                    skipped_count=$((skipped_count + 1))
                else
                    passed_count=$((passed_count + 1))
                fi
                ;;
            failed)
                failed_count=$((failed_count + 1))
                overall="failed"
                ;;
            *)
                failed_count=$((failed_count + 1))
                overall="unknown"
                ;;
        esac
    done
    
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
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "overall": "$overall",
  "summary": {
    "passed": $passed_count,
    "failed": $failed_count,
    "skipped": $skipped_count,
    "total": $total
  },
  "gates": {$gates_json}
}
EOF
}

output_summary() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "                 GATE RUNNER SUMMARY                           "
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    
    local passed=0
    local failed=0
    
    for gate in $GATE_ORDER; do
        local status
        status=$(get_result "$gate")
        local message
        message=$(get_message "$gate")
        
        case "$status" in
            passed)
                echo -e "  ${GREEN}✓${NC} $gate${NC}"
                passed=$((passed + 1))
                ;;
            failed)
                echo -e "  ${RED}✗${NC} $gate - $message${NC}"
                failed=$((failed + 1))
                ;;
            *)
                echo -e "  ${YELLOW}?${NC} $gate - $status${NC}"
                failed=$((failed + 1))
                ;;
        esac
    done
    
    echo ""
    echo "───────────────────────────────────────────────────────────────"
    echo -e "  ${GREEN}Passed:${NC}  $passed"
    echo -e "  ${RED}Failed:${NC}  $failed"
    echo "───────────────────────────────────────────────────────────────"
    echo ""
    
    if [[ $failed -eq 0 ]]; then
        echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║           ALL GATES PASSED - Ready for release          ║${NC}"
        echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
        return 0
    else
        echo -e "${RED}╔══════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║        $failed GATE(S) FAILED - Fix before release                ║${NC}"
        echo -e "${RED}╚══════════════════════════════════════════════════════════╝${NC}"
        return 1
    fi
}

# =============================================================================
# CLI ARGUMENT PARSING
# =============================================================================

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --output|-o)
                OUTPUT_FORMAT="$2"
                shift 2
                ;;
            --skip)
                SKIP_GATES="$2"
                shift 2
                ;;
            --help|-h)
                cat <<EOF
Usage: $SCRIPT_NAME [OPTIONS]

Options:
  --output, -o FORMAT   Output format: json (default) or summary
  --skip GATES          Comma-separated list of gates to skip
  --help, -h            Show this help message

Gates (in order):
  lint        - ruff check
  format      - ruff format --check
  type        - pyright type check
  unit        - pytest unit tests
  integration - pytest integration tests
  go-dnstap   - Go tests for dnstap-processor
  go-sync     - Go tests for sync-agent
  build       - docker compose build
  smoke       - health check and DNS query verification

Examples:
  $SCRIPT_NAME                          # Run all gates, output JSON
  $SCRIPT_NAME --output summary         # Run all gates, human-readable output
  $SCRIPT_NAME --skip smoke,build       # Skip smoke and build gates
  $SCRIPT_NAME --output json --skip smoke

Exit Codes:
  0 - All gates passed
  1 - One or more gates failed
  2 - Prerequisites not met
EOF
                exit 0
                ;;
            *)
                log_fail "Unknown option: $1"
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
    
    # Initialize temp files
    RESULTS_FILE=$(mktemp)
    MESSAGES_FILE=$(mktemp)
    
    # Initialize all gates
    for gate in $GATE_ORDER; do
        echo "${gate}=unknown" >> "$RESULTS_FILE"
        echo "${gate}=" >> "$MESSAGES_FILE"
    done
    
    echo "" >&2
    echo "╔═══════════════════════════════════════════════════════════════╗" >&2
    echo "║        PowerBlockade Local Gate Runner                        ║" >&2
    echo "╚═══════════════════════════════════════════════════════════════╝" >&2
    echo "" >&2
    
    if ! check_prerequisites; then
        log_fail "Prerequisites not met. Please install missing dependencies."
        exit 2
    fi
    
    log_info "Prerequisites OK"
    
    local any_failed=0
    
    gate_lint || any_failed=1
    gate_format || any_failed=1
    gate_type || any_failed=1
    gate_unit || any_failed=1
    gate_integration || any_failed=1
    gate_go_dnstap || any_failed=1
    gate_go_sync || any_failed=1
    gate_build || any_failed=1
    gate_smoke || any_failed=1
    
    if [[ "$OUTPUT_FORMAT" == "json" ]]; then
        output_json
    else
        output_summary
    fi
    
    if [[ $any_failed -eq 1 ]]; then
        exit 1
    fi
    
    exit 0
}

main "$@"
