#!/usr/bin/env bash
#
# dns53-benchmark.sh - PowerBlockade DNS Performance Benchmark Suite
#
# Measures DNS resolution performance across four phases:
#   1. Cold cache    - baseline resolution performance (both cache layers cleared)
#   2. Warm cache    - cached resolution performance
#   3. Saturation    - sustained maximum throughput / stress test
#   4. Time-to-warm  - elapsed time from cold until p99 AND per-layer cache hit
#                      ratios hold within target for N consecutive windows
#
# USAGE:
#   ./dns53-benchmark.sh --target 127.0.0.1 --mode all --output json
#   ./dns53-benchmark.sh --help
#   ./dns53-benchmark.sh --self-test
#
# CONTRACT: See docs/performance/dns-benchmark-methodology.md for full specification
#
# EXIT CODES:
#   0 - All phases passed (no regressions detected)
#   1 - One or more phases failed (performance regression or parse failure)
#   2 - Prerequisites not met (missing tools, no network access, failed clear)
#   3 - Configuration error (invalid arguments, missing files)
#
# OUTPUT FORMATS:
#   --output json     - Machine-readable JSON for regression gates
#   --output markdown - Human-readable summary for reports
#   --output both     - Generate both formats
#
# CLEARING CONTRACT (fail-closed):
#   "Cold" runs must clear BOTH cache layers (dnsdist packet cache AND the
#   recursor record/packet caches) before any dnsperf traffic is sent. Every
#   clearing step is verified; a failed or unverifiable clear aborts the run
#   BEFORE dnsperf. Cache-hit ratios are computed from counter DELTAS
#   (post-run minus pre-run snapshot), never from absolute counters.
#
# =============================================================================

set -uo pipefail

# =============================================================================
# SCRIPT METADATA
# =============================================================================

readonly SCRIPT_NAME="dns53-benchmark.sh"
readonly SCRIPT_VERSION="2.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly PROJECT_ROOT

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

# How to clear the caches for cold / time-to-warm phases.
#   console - non-disruptive: dnsdist console (`expunge(0)`) + rec_control
#             `wipe-cache '$'` (default). Requires DNSDIST_CONSOLE_KEY on the
#             dnsdist container; fails closed with instructions when absent.
#   restart - DESTRUCTIVE opt-in: `docker restart` of the dnsdist and recursor
#             containers, then bounded wait for BOTH to report healthy before
#             any counters are taken or traffic is sent.
CLEAR_MODE="${DNS53_BENCHMARK_CLEAR_MODE:-console}"

# Time-to-warm detection: N consecutive windows of W seconds must all hold
# p99 <= DNS53_TTW_P99_THRESHOLD_MS and every measured layer's window hit
# ratio >= its target before the stack counts as "warm".
TTW_WINDOWS="${DNS53_TTW_WINDOWS:-5}"
TTW_WINDOW_SECONDS="${DNS53_TTW_WINDOW_SECONDS:-30}"
TTW_QPS="${DNS53_TTW_QPS:-500}"
TTW_MAX_WINDOWS="${DNS53_TTW_MAX_WINDOWS:-40}"

# Container names (compose stack). Override for non-default deployments.
DNSDIST_CONTAINER="${DNSDIST_CONTAINER:-powerblockade-dnsdist}"
RECURSOR_CONTAINER="${RECURSOR_CONTAINER:-powerblockade-recursor}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-powerblockade-postgres}"
DNSTAP_CONTAINER="${DNSTAP_CONTAINER:-powerblockade-dnstap-processor}"
POSTGRES_USER="${PB_POSTGRES_USER:-powerblockade}"
POSTGRES_DB="${PB_POSTGRES_DB:-powerblockade}"
readonly RECURSOR_SOCKET_DIR="/var/run/pdns-recursor"

# Optional HTTP statistics sources (integration branch exposes these on the
# compose network only; the harness defaults to docker-exec based collection
# which works from the host on every branch):
#   DNSDIST_STATS_URL     e.g. http://127.0.0.1:8083  -> /jsonstat (basic auth)
#   DNSDIST_WEB_PASSWORD  basic-auth password for the dnsdist webserver
#   RECURSOR_METRICS_URL  e.g. http://127.0.0.1:8082  -> /metrics (basic auth)
#   RECURSOR_WEB_PASSWORD basic-auth password for the recursor webserver
DNSDIST_STATS_URL="${DNSDIST_STATS_URL:-}"
DNSDIST_WEB_PASSWORD="${DNSDIST_WEB_PASSWORD:-}"
RECURSOR_METRICS_URL="${RECURSOR_METRICS_URL:-}"
RECURSOR_WEB_PASSWORD="${RECURSOR_WEB_PASSWORD:-}"

# Precache warming quiesce: pause the admin-ui precache warming job during
# measurement phases by flipping settings.precache_enabled to false (the
# scheduler job re-reads the setting each time it fires, every 5 minutes).
# Toggle is done with psql via docker exec (same pattern as the operations
# runbook); the /precache/settings HTTP endpoint requires an admin session and
# rewrites every precache field, so it is not harness-safe.
PRECACHE_PAUSE="${DNS53_PRECACHE_PAUSE:-true}"
STRICT_QUIESCE="${DNS53_STRICT_QUIESCE:-false}"

# Default corpus paths (relative to project root)
DEFAULT_CONTROL_CORPUS="docs/performance/corpus/control-domains.txt"

# Minimum dnsperf version. 2.14.0 introduced `-O latency-histogram`, which is
# the only supported way to compute percentiles (verified against the 2.14.0
# and 2.16.0 sources/output; dnsperf has no JSON output at any version - the
# old `-o json` invocation was invalid and silently produced nothing).
DNSPERF_MIN_VERSION="2.14.0"

# Performance thresholds (for pass/fail determination)
# These can be overridden via environment variables
COLD_P50_THRESHOLD="${DNS53_COLD_P50_THRESHOLD_MS:-20}"
COLD_P95_THRESHOLD="${DNS53_COLD_P95_THRESHOLD_MS:-100}"
COLD_P99_THRESHOLD="${DNS53_COLD_P99_THRESHOLD_MS:-200}"
WARM_P50_THRESHOLD="${DNS53_WARM_P50_THRESHOLD_MS:-5}"
WARM_P95_THRESHOLD="${DNS53_WARM_P95_THRESHOLD_MS:-20}"
WARM_P99_THRESHOLD="${DNS53_WARM_P99_THRESHOLD_MS:-50}"
WARM_CACHE_HIT_THRESHOLD="${DNS53_WARM_CACHE_HIT_PCT:-90}"
SATURATION_MIN_QPS="${DNS53_SATURATION_MIN_QPS:-5000}"
TTW_P99_THRESHOLD="${DNS53_TTW_P99_THRESHOLD_MS:-50}"
TTW_DNSDIST_HIT_PCT="${DNS53_TTW_DNSDIST_HIT_PCT:-90}"
TTW_PACKETCACHE_HIT_PCT="${DNS53_TTW_PACKETCACHE_HIT_PCT:-90}"
TTW_RECCACHE_HIT_PCT="${DNS53_TTW_RECCACHE_HIT_PCT:-90}"

# Health-wait bound (seconds) when --clear-mode=restart restarts containers.
RESTART_HEALTH_TIMEOUT="${DNS53_RESTART_HEALTH_TIMEOUT:-180}"

# =============================================================================
# EXIT CODES (Contract)
# =============================================================================

readonly EXIT_SUCCESS=0          # All phases passed
readonly EXIT_PHASE_FAILED=1     # One or more phases failed (regression/parse)
readonly EXIT_PREREQ_FAILED=2    # Prerequisites not met (incl. failed clear)
readonly EXIT_CONFIG_ERROR=3     # Configuration error

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
                            Values: cold, warm, saturation, time-to-warm, all

    --clear-mode <mode>     Cache clearing strategy for cold/time-to-warm
                            (default: console)
                              console - dnsdist console expunge(0) +
                                        rec_control wipe-cache '$' (non-disruptive;
                                        requires DNSDIST_CONSOLE_KEY, fails closed)
                              restart - DESTRUCTIVE: docker restart dnsdist+recursor,
                                        waits for both healthy before counting.
                                        Anything else is refused (exit 3).

    --target <host>         DNS server address (default: 127.0.0.1)

    --port <port>           DNS server port (default: 53)

    --corpus <path>         Path to domain corpus file (default: auto-detect)

    --duration <seconds>    Duration per phase in seconds (default: 60)

    --warm-windows <n>      Time-to-warm: consecutive passing windows required
                            (default: 5)

    --warm-window-seconds <s>
                            Time-to-warm: window length in seconds (default: 30)

    --ttw-qps <qps>         Time-to-warm: load level during warming (default: 500)

    --no-precache-pause     Do not pause the admin-ui precache warming job
                            (default: pause during measurement via
                            settings.precache_enabled=false, restored after)

    --strict-quiesce        Fail (exit 2) if the precache job cannot be paused
                            instead of degrading with a warning

    --output <format>       Output format (default: json)
                            Values: json, markdown, both

    --results-dir <path>    Directory to save results (default: results/)

    --self-test             Run the offline test suite (no docker, no dnsperf,
                            no network) and exit

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
    DNS53_BENCHMARK_CLEAR_MODE Default clear mode

    DNSDIST_CONTAINER          dnsdist container (default: powerblockade-dnsdist)
    RECURSOR_CONTAINER         recursor container (default: powerblockade-recursor)
    POSTGRES_CONTAINER         postgres container (default: powerblockade-postgres)
    DNSTAP_CONTAINER           dnstap-processor container
                               (default: powerblockade-dnstap-processor)
    PB_POSTGRES_USER / PB_POSTGRES_DB
                               postgres user/database (default: powerblockade)

    DNSDIST_STATS_URL / DNSDIST_WEB_PASSWORD
                               Optional dnsdist /jsonstat endpoint (basic auth,
                               any username). Default: dnsdist console.
    RECURSOR_METRICS_URL / RECURSOR_WEB_PASSWORD
                               Optional recursor /metrics endpoint (basic auth,
                               any username). Default: rec_control via docker exec.

    # Thresholds (for pass/fail determination):
    DNS53_COLD_P50_THRESHOLD_MS    Cold p50 latency threshold (default: 20)
    DNS53_COLD_P95_THRESHOLD_MS    Cold p95 latency threshold (default: 100)
    DNS53_COLD_P99_THRESHOLD_MS    Cold p99 latency threshold (default: 200)
    DNS53_WARM_P50_THRESHOLD_MS    Warm p50 latency threshold (default: 5)
    DNS53_WARM_P95_THRESHOLD_MS    Warm p95 latency threshold (default: 20)
    DNS53_WARM_P99_THRESHOLD_MS    Warm p99 latency threshold (default: 50)
    DNS53_WARM_CACHE_HIT_PCT       Warm packet-cache hit ratio threshold (default: 90)
    DNS53_SATURATION_MIN_QPS       Minimum QPS for saturation pass (default: 5000)
    DNS53_TTW_P99_THRESHOLD_MS     Time-to-warm p99 target (default: 50)
    DNS53_TTW_DNSDIST_HIT_PCT      Time-to-warm dnsdist hit target (default: 90)
    DNS53_TTW_PACKETCACHE_HIT_PCT  Time-to-warm packetcache hit target (default: 90)
    DNS53_TTW_RECCACHE_HIT_PCT     Time-to-warm record-cache hit target (default: 90)
    DNS53_TTW_WINDOWS / DNS53_TTW_WINDOW_SECONDS / DNS53_TTW_QPS
                                   Time-to-warm detection parameters
                                   (default: 5 windows x 30s at 500 QPS)
    DNS53_RESTART_HEALTH_TIMEOUT   restart-mode health wait bound (default: 180s)

EXIT CODES:
    0    All phases passed (no regressions detected)
    1    One or more phases failed (performance regression or parse failure)
    2    Prerequisites not met (missing tools, no network access, failed clear)
    3    Configuration error (invalid arguments, missing files)

EXAMPLES:
    # Run all benchmarks against the local compose stack (console clearing)
    DNSDIST_CONSOLE_KEY=$(grep DNSDIST_CONSOLE_KEY .env | cut -d= -f2) \
        ./scripts/benchmarks/dns53-benchmark.sh --mode all

    # Destructive restart-based clearing (explicit opt-in)
    ./scripts/benchmarks/dns53-benchmark.sh --mode cold --clear-mode restart

    # Time-to-warm measurement (5 consecutive 30s windows at 500 QPS)
    ./scripts/benchmarks/dns53-benchmark.sh --mode time-to-warm

    # Offline validation of the harness itself
    ./scripts/benchmarks/dns53-benchmark.sh --self-test

PREREQUISITES:
    - dnsperf >= 2.14.0  (2.14.0 added -O latency-histogram; percentiles are
      computed from the histogram. dnsperf has NO JSON output - any earlier
      parse fallback silently nulled percentiles, which is now a hard error)
    - jq
    - docker (for cache clearing and counter collection against the compose
      stack; the harness reports a clear error if a source is unavailable)
    - dig, bc

DOCUMENTATION:
    Full methodology: docs/performance/dns-benchmark-methodology.md
    Cache operations: docs/performance/dns-cache-operations-runbook.md

EOF
}

show_version() {
    echo "${SCRIPT_NAME} version ${SCRIPT_VERSION}"
}

# =============================================================================
# ARGUMENT VALIDATION
# =============================================================================

validate_args() {
    local errors=0

    case "$MODE" in
        cold|warm|saturation|time-to-warm|all) ;;
        *)
            log_fail "Invalid mode: $MODE (expected: cold, warm, saturation, time-to-warm, all)"
            errors=$((errors + 1))
            ;;
    esac

    case "$CLEAR_MODE" in
        console|restart) ;;
        *)
            log_fail "Unrecognized --clear-mode target: '$CLEAR_MODE'"
            log_info "Refusing to clear anything. Valid values: console, restart"
            log_info "restart is DESTRUCTIVE (docker restart dnsdist+recursor) and must be requested explicitly"
            errors=$((errors + 1))
            ;;
    esac

    case "$OUTPUT" in
        json|markdown|both) ;;
        *)
            log_fail "Invalid output format: $OUTPUT (expected: json, markdown, both)"
            errors=$((errors + 1))
            ;;
    esac

    if ! [[ "$DURATION" =~ ^[0-9]+$ ]] || [[ "$DURATION" -lt 1 ]]; then
        log_fail "Invalid duration: $DURATION (expected: positive integer)"
        errors=$((errors + 1))
    fi

    if ! [[ "$TTW_WINDOWS" =~ ^[0-9]+$ ]] || [[ "$TTW_WINDOWS" -lt 1 ]]; then
        log_fail "Invalid --warm-windows: $TTW_WINDOWS (expected: positive integer)"
        errors=$((errors + 1))
    fi

    if ! [[ "$TTW_WINDOW_SECONDS" =~ ^[0-9]+$ ]] || [[ "$TTW_WINDOW_SECONDS" -lt 5 ]]; then
        log_fail "Invalid --warm-window-seconds: $TTW_WINDOW_SECONDS (expected: integer >= 5)"
        errors=$((errors + 1))
    fi

    if ! [[ "$TTW_QPS" =~ ^[0-9]+$ ]] || [[ "$TTW_QPS" -lt 1 ]]; then
        log_fail "Invalid --ttw-qps: $TTW_QPS (expected: positive integer)"
        errors=$((errors + 1))
    fi

    if [[ $errors -gt 0 ]]; then
        return $EXIT_CONFIG_ERROR
    fi
    return 0
}

# =============================================================================
# VERSION HELPERS
# =============================================================================

# version_ge <a> <b>: numeric dot-version compare, true when a >= b.
# Non-numeric suffixes (e.g. "2.16.0-dev") are stripped per component.
version_ge() {
    local a="$1" b="$2"
    local -a av bv
    IFS=. read -r -a av <<< "$a"
    IFS=. read -r -a bv <<< "$b"
    local i
    for i in 0 1 2; do
        local x="${av[i]:-0}" y="${bv[i]:-0}"
        x="${x%%[^0-9]*}"; y="${y%%[^0-9]*}"
        x=$((10#${x:-0})); y=$((10#${y:-0}))
        if (( x > y )); then return 0; fi
        if (( x < y )); then return 1; fi
    done
    return 0
}

# dnsperf_version_probe: dnsperf builds disagree on version flags. Some print
# it on `-V`; Fedora/2.15.0 rejects `-V`/`--version` and only prints the
# version in the run banner. Probe in order: -V, -h, then a 1-query throwaway
# run against the loopback with an empty datafile (prints the banner, exits
# immediately). Return the first X.Y.Z found; empty string if none.
dnsperf_version_probe() {
    local out
    out=$(dnsperf -V 2>&1 | head -2)
    local v
    v=$(parse_dnsperf_version "$out")
    [[ -n "$v" ]] && { printf '%s\n' "$v"; return 0; }
    out=$(dnsperf -h 2>&1 | head -3)
    v=$(parse_dnsperf_version "$out")
    [[ -n "$v" ]] && { printf '%s\n' "$v"; return 0; }
    out=$(dnsperf -s 127.0.0.1 -l 1 </dev/null 2>&1 | head -3)
    parse_dnsperf_version "$out"
}

# parse_dnsperf_version <text>: extract X.Y.Z from dnsperf output.
parse_dnsperf_version() {
    printf '%s\n' "$1" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1
}

# =============================================================================
# PREREQUISITE CHECKS (Contract)
# =============================================================================

PREREQ_JSON='{}'
DNSPERF_VERSION=""

check_prerequisites() {
    local errors=0
    local prereq_json="{"

    log_section "Prerequisite Checks"

    # Check dnsperf
    if command -v dnsperf &>/dev/null; then
        DNSPERF_VERSION=$(dnsperf_version_probe)
        if [[ -z "$DNSPERF_VERSION" ]]; then
            log_fail "dnsperf installed but version could not be parsed (tried -V, -h, and run banner)"
            prereq_json+="\"dnsperf\": {\"installed\": true, \"version\": \"unknown\"}, "
            errors=$((errors + 1))
        elif version_ge "$DNSPERF_VERSION" "$DNSPERF_MIN_VERSION"; then
            log_pass "dnsperf installed (version: $DNSPERF_VERSION >= $DNSPERF_MIN_VERSION)"
            prereq_json+="\"dnsperf\": {\"installed\": true, \"version\": \"$DNSPERF_VERSION\"}, "
        else
            log_fail "dnsperf $DNSPERF_VERSION is too old (need >= $DNSPERF_MIN_VERSION for -O latency-histogram)"
            log_info "dnsperf has no JSON output at any version; percentiles require the latency histogram"
            prereq_json+="\"dnsperf\": {\"installed\": true, \"version\": \"$DNSPERF_VERSION\", \"min_required\": \"$DNSPERF_MIN_VERSION\"}, "
            errors=$((errors + 1))
        fi
    else
        log_fail "dnsperf not installed (need >= $DNSPERF_MIN_VERSION)"
        prereq_json+="\"dnsperf\": {\"installed\": false}, "
        errors=$((errors + 1))
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

    # Check dig
    if command -v dig &>/dev/null; then
        log_pass "dig installed"
        prereq_json+="\"dig\": {\"installed\": true}, "
    else
        log_fail "dig not installed (required for network preflight)"
        prereq_json+="\"dig\": {\"installed\": false}, "
        errors=$((errors + 1))
    fi

    # docker is required for cache clearing / counter collection on this stack
    if command -v docker &>/dev/null; then
        if docker info &>/dev/null; then
            log_pass "docker available"
            prereq_json+="\"docker\": {\"installed\": true}, "
        else
            log_fail "docker CLI present but the daemon is not reachable"
            prereq_json+="\"docker\": {\"installed\": true, \"daemon\": false}, "
            errors=$((errors + 1))
        fi
    else
        log_fail "docker not installed (required to clear/inspect the compose stack)"
        prereq_json+="\"docker\": {\"installed\": false}, "
        errors=$((errors + 1))
    fi

    # Check network access to target
    local latency_ms
    if latency_ms=$(check_network_access); then
        log_pass "Network access to $TARGET:$PORT (latency: ${latency_ms}ms)"
        prereq_json+="\"network_access\": {\"ok\": true, \"latency_ms\": $latency_ms}"
    else
        log_fail "Cannot reach $TARGET:$PORT"
        prereq_json+="\"network_access\": {\"ok\": false}"
        errors=$((errors + 1))
    fi

    prereq_json+="}"
    PREREQ_JSON="$prereq_json"

    if [[ $errors -gt 0 ]]; then
        return $EXIT_PREREQ_FAILED
    fi
    return 0
}

check_network_access() {
    local start_ns end_ns latency_ns latency_ms

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

    # Validate corpus file
    if [[ -n "$CORPUS" ]]; then
        if [[ -f "$CORPUS" ]]; then
            log_pass "Corpus: $CORPUS"
        else
            log_fail "Corpus file not found: $CORPUS"
            errors=$((errors + 1))
        fi
    else
        # Auto-detect corpus
        if [[ -f "${PROJECT_ROOT}/${DEFAULT_CONTROL_CORPUS}" ]]; then
            CORPUS="${PROJECT_ROOT}/${DEFAULT_CONTROL_CORPUS}"
            log_pass "Corpus (auto-detected): $CORPUS"
        else
            log_fail "No corpus specified and default not found: ${DEFAULT_CONTROL_CORPUS}"
            log_info "Create a corpus file or specify --corpus <path>"
            errors=$((errors + 1))
        fi
    fi

    if [[ -z "$TARGET" ]]; then
        log_fail "Target not specified"
        errors=$((errors + 1))
    else
        log_pass "Target: ${TARGET}:${PORT}"
    fi

    # Create results directory if needed
    if ! mkdir -p "$RESULTS_DIR" 2>/dev/null; then
        log_fail "Cannot create results directory: $RESULTS_DIR"
        errors=$((errors + 1))
    fi

    if [[ $errors -gt 0 ]]; then
        return $EXIT_CONFIG_ERROR
    fi
    return 0
}

# =============================================================================
# BENCHMARK PHASE RESULT STORAGE
# =============================================================================

COLD_CACHE_RESULT="null"
WARM_CACHE_RESULT="null"
SATURATION_RESULT="null"
TTW_RESULT="null"
PHASES_RUN=0
PHASES_PASSED=0
PHASES_FAILED=0
ABORT_REMAINING_PHASES=false
CLEAR_FAILED=false
REGRESSIONS=()

push_regression() {
    REGRESSIONS+=("$1")
}

# json_array_from_list <item>...: build a JSON array of strings
json_array_from_list() {
    if [[ $# -gt 0 ]]; then
        printf '%s\n' "$@" | jq -R . | jq -s .
    else
        echo "[]"
    fi
}

# =============================================================================
# CONTAINER / DOCKER HELPERS
# =============================================================================

container_state() {
    # Prints the docker container state (running/exists) or "missing".
    docker inspect --format='{{.State.Status}}' "$1" 2>/dev/null || echo "missing"
}

container_health() {
    # Prints HealthStatus or "none" when the container has no healthcheck.
    docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1" 2>/dev/null || echo "missing"
}

container_running() {
    [[ "$(container_state "$1")" == "running" ]]
}

# wait_container_healthy <name> <timeout_seconds>: bounded wait until the
# container reports healthy (containers without a healthcheck count as healthy
# once running). Returns 1 on timeout.
wait_container_healthy() {
    local name="$1" timeout="$2"
    local waited=0 status
    while (( waited < timeout )); do
        status="$(container_health "$name")"
        case "$status" in
            healthy)
                return 0
                ;;
            none)
                if container_running "$name"; then return 0; fi
                ;;
            missing)
                log_fail "Container $name disappeared while waiting for health"
                return 1
                ;;
        esac
        sleep 2
        waited=$((waited + 2))
    done
    log_fail "Container $name not healthy after ${timeout}s (last status: $status)"
    return 1
}

# =============================================================================
# STATISTICS SOURCES (per layer, with clean degradation)
# =============================================================================
# Counter sources, tried in order per layer. Whatever works is recorded in
# STATS_SOURCES_JSON and reported in the result JSON. When NO source works for
# a layer that a phase requires, the run fails closed with a clear message
# BEFORE any dnsperf traffic is sent (no unmeasurable runs).
#
#   dnsdist:
#     1. DNSDIST_STATS_URL + DNSDIST_WEB_PASSWORD -> GET <url>/jsonstat
#        (basic auth, any username; integration branch exposes :8083 on the
#        compose network only)
#     2. dnsdist console via docker exec (same DNSDIST_CONSOLE_KEY
#        prerequisite as clearing): getPool(''):getCache():getStats()
#   recursor:
#     1. RECURSOR_METRICS_URL + RECURSOR_WEB_PASSWORD -> GET <url>/metrics
#     2. docker exec rec_control get <stats...> (values only, order preserved)

STATS_SOURCES_JSON='{"dnsdist": null, "recursor": null}'
STATS_DD_SOURCE=""
STATS_REC_SOURCE=""

# fetch_jsonstat_dnsdist: sets DD_RAW on success
fetch_dnsdist_jsonstat() {
    [[ -n "$DNSDIST_STATS_URL" && -n "$DNSDIST_WEB_PASSWORD" ]] || return 3
    curl -sf -m 10 -u "admin:${DNSDIST_WEB_PASSWORD}" \
        "${DNSDIST_STATS_URL%/}/jsonstat" 2>/dev/null || return 1
}

# fetch_console_dnsdist: runs the console client; echoes combined output.
fetch_dnsdist_console_stats() {
    docker exec "$DNSDIST_CONTAINER" \
        dnsdist -c -C /tmp/dnsdist.conf \
        -e "getPool(''):getCache():getStats()" 2>&1 || return 1
}

# fetch_recursor_metrics: curl the Prometheus endpoint
fetch_recursor_metrics() {
    [[ -n "$RECURSOR_METRICS_URL" && -n "$RECURSOR_WEB_PASSWORD" ]] || return 3
    curl -sf -m 10 -u "metrics:${RECURSOR_WEB_PASSWORD}" \
        "${RECURSOR_METRICS_URL%/}/metrics" 2>/dev/null || return 1
}

# fetch_recursor_reccontrol: rec_control get; values only, one per line,
# in the requested order (rec_channel_rec.cc doGet prints bare values).
REC_CONTROL_STATS="cache-hits cache-misses cache-entries max-cache-entries packetcache-hits packetcache-misses packetcache-entries max-packetcache-entries"
fetch_recursor_reccontrol() {
    docker exec "$RECURSOR_CONTAINER" \
        rec_control --socket-dir="$RECURSOR_SOCKET_DIR" \
        get $REC_CONTROL_STATS 2>/dev/null || return 1
}

# parse_rec_control_values <raw> <expected_count>: validates that every line is
# numeric and the count matches; echoes space-separated values; rc 1 on any
# "UNKNOWN" or malformed line (fail-closed).
parse_rec_control_values() {
    local raw="$1" expected="$2"
    local values=""
    local count=0 line
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        if [[ "$line" == "UNKNOWN" ]] || ! [[ "$line" =~ ^[0-9]+$ ]]; then
            return 1
        fi
        values+="$line "
        count=$((count + 1))
    done <<< "$raw"
    if [[ "$count" -ne "$expected" ]]; then
        return 1
    fi
    echo "${values% }"
}

# collect_stats: unified per-layer snapshot into STATS_JSON (global).
# Shape:
# {
#   "dnsdist":  {"hits":N,"misses":N,"entries":N,"maxEntries":N} | null,
#   "recursor": {"packetcache_hits":N,"packetcache_misses":N,"cache_hits":N,
#                "cache_misses":N,"cache_entries":N,"packetcache_entries":N,
#                "max_cache_entries":N,"max_packetcache_entries":N} | null
# }
collect_stats() {
    STATS_JSON='{"dnsdist": null, "recursor": null}'
    local dd_json="null" rec_json="null" raw

    # --- dnsdist layer -----------------------------------------------------
    if raw=$(fetch_dnsdist_jsonstat); then
        dd_json=$(printf '%s' "$raw" | jq -c '([.pools[] | select(.name == "")] | first) // {} |
            if has("cacheHits") then
                {hits: (.cacheHits // 0), misses: (.cacheMisses // 0),
                 entries: (.cacheEntries // 0), maxEntries: (.cacheSize // 0)}
            else null end' 2>/dev/null)
        if [[ "$dd_json" != "null" && -n "$dd_json" ]]; then
            STATS_DD_SOURCE="jsonstat"
        else
            dd_json="null"
        fi
    fi
    if [[ "$dd_json" == "null" ]]; then
        if raw=$(fetch_dnsdist_console_stats); then
            # Console prints the stats table as a single JSON object line
            # (verified on dnsdist 2.0.8). Earlier non-JSON lines are config
            # parse noise and are ignored.
            local line
            while IFS= read -r line; do
                if [[ "$line" == \{* ]]; then
                    dd_json=$(printf '%s' "$line" | jq -c '{hits: (.hits // 0), misses: (.misses // 0), entries: (.entries // 0), maxEntries: (.maxEntries // 0)}' 2>/dev/null)
                fi
            done <<< "$raw"
            if [[ -n "$dd_json" && "$dd_json" != "null" ]]; then
                STATS_DD_SOURCE="dnsdist-console"
            else
                dd_json="null"
            fi
        fi
    fi

    # --- recursor layer ----------------------------------------------------
    if raw=$(fetch_recursor_metrics); then
        rec_json=$(printf '%s' "$raw" | awk '
            /^pdns_recursor_(cache_hits|cache_misses|cache_entries|max_cache_entries|packetcache_hits|packetcache_misses|packetcache_entries|max_packetcache_entries)[[:space:]]/ {
                gsub("-", "_", $1); sub(/^pdns_recursor_/, "", $1); v[$1] = $2
            }
            END {
                if ("cache_hits" in v)
                    printf "{\"packetcache_hits\": %s, \"packetcache_misses\": %s, \"cache_hits\": %s, \"cache_misses\": %s, \"cache_entries\": %s, \"packetcache_entries\": %s, \"max_cache_entries\": %s, \"max_packetcache_entries\": %s}",
                        v["packetcache_hits"]+0, v["packetcache_misses"]+0, v["cache_hits"]+0, v["cache_misses"]+0, v["cache_entries"]+0, v["packetcache_entries"]+0, v["max_cache_entries"]+0, v["max_packetcache_entries"]+0
            }')
        if [[ -n "$rec_json" ]]; then
            STATS_REC_SOURCE="metrics-url"
        else
            rec_json="null"
        fi
    fi
    if [[ "$rec_json" == "null" || -z "$rec_json" ]]; then
        if raw=$(fetch_recursor_reccontrol); then
            local values
            if values=$(parse_rec_control_values "$raw" 8); then
                local -a v
                read -r -a v <<< "$values"
                rec_json=$(jq -n \
                    --argjson pch "${v[4]}" --argjson pcm "${v[5]}" \
                    --argjson ch  "${v[0]}" --argjson cm  "${v[1]}" \
                    --argjson ce  "${v[2]}" --argjson mce "${v[3]}" \
                    --argjson pce "${v[6]}" --argjson mpce "${v[7]}" \
                    '{packetcache_hits: $pch, packetcache_misses: $pcm,
                      cache_hits: $ch, cache_misses: $cm,
                      cache_entries: $ce, packetcache_entries: $pce,
                      max_cache_entries: $mce, max_packetcache_entries: $mpce}')
                STATS_REC_SOURCE="rec_control"
            else
                rec_json="null"
            fi
        fi
    fi

    STATS_JSON=$(jq -cn --argjson dd "$dd_json" --argjson rec "$rec_json" \
        '{dnsdist: $dd, recursor: $rec}')
    STATS_SOURCES_JSON=$(jq -cn \
        --arg dd "$STATS_DD_SOURCE" --arg rec "$STATS_REC_SOURCE" \
        '{dnsdist: (if $dd == "" then null else $dd end),
          recursor: (if $rec == "" then null else $rec end)}')
}

# stats_source_for <layer>: "" | source name
require_stats_sources() {
    # Fails (returns 1, with messages) when a layer needed by the current mode
    # has no working counter source. dnsdist+recursor are both required for
    # cold / warm / time-to-warm (floor verification and per-layer ratios).
    local missing=()
    if [[ -z "$STATS_DD_SOURCE" ]]; then
        missing+=("dnsdist")
        log_fail "No working statistics source for the dnsdist layer"
        log_info "Set DNSDIST_STATS_URL + DNSDIST_WEB_PASSWORD (integration branch webserver)"
        log_info "or enable the dnsdist console: set DNSDIST_CONSOLE_KEY in .env and recreate the dnsdist container"
    fi
    if [[ -z "$STATS_REC_SOURCE" ]]; then
        missing+=("recursor")
        log_fail "No working statistics source for the recursor layer"
        log_info "Set RECURSOR_METRICS_URL + RECURSOR_WEB_PASSWORD (integration branch webserver)"
        log_info "or ensure the recursor container is reachable via: docker exec $RECURSOR_CONTAINER rec_control --socket-dir=$RECURSOR_SOCKET_DIR ping"
    fi
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_fail "Counter sources missing for: ${missing[*]} - aborting before any dnsperf traffic (unmeasurable run)"
        return 1
    fi
    log_pass "Counter sources: dnsdist=$STATS_DD_SOURCE recursor=$STATS_REC_SOURCE"
    return 0
}

# =============================================================================
# CACHE FLOOR VERIFICATION (fail-closed)
# =============================================================================

# Cache floor tolerance for the recursor side: the recursor's built-in
# housekeeping (security-status poll for recursor-<v>.security-status.secpoll
# .powerdns.com, root refresh) legitimately repopulates the cache within
# seconds of a wipe. On a fully primed live recursor the quiescent steady
# state is ~57 entries (13 root NS + A/AAAA glue + security-status poll;
# observed live with zero query traffic). Those domains cannot intersect a
# benchmark corpus, so a bounded occupancy counts as "empty" — 128 leaves
# two orders of magnitude below a FAILED wipe (observed pre-wipe: ~14k
# entries), which this check exists to catch. The dnsdist packet cache has
# no background self-queries and is held to a strict zero.
RECURSOR_FLOOR_TOLERANCE="${DNS53_RECURSOR_FLOOR_TOLERANCE:-128}"

# verify_cache_floor <stats_json>: all measured cache layers must be EMPTY.
# This is the authoritative success signal for clearing (tool exit codes are
# unreliable: the dnsdist console client exits 0 even on auth failure).
# dnsdist: entries must be 0. recursor: entries within the tolerance above
# (observed count is reported; anything larger fails closed).
verify_cache_floor() {
    local stats="$1"
    local failed=0

    local dd_entries
    dd_entries=$(jq -r '.dnsdist.entries // "absent"' <<< "$stats" 2>/dev/null)
    if [[ "$dd_entries" == "absent" ]]; then
        log_fail "Cache floor check: dnsdist stats unavailable (no counter source)"
        failed=1
    elif (( dd_entries > 0 )); then
        log_fail "Cache floor check: dnsdist packet cache still holds $dd_entries entries"
        failed=1
    fi

    local rec_ce rec_pce
    rec_ce=$(jq -r '.recursor.cache_entries // "absent"' <<< "$stats" 2>/dev/null)
    rec_pce=$(jq -r '.recursor.packetcache_entries // "absent"' <<< "$stats" 2>/dev/null)
    if [[ "$rec_ce" == "absent" || "$rec_pce" == "absent" ]]; then
        log_fail "Cache floor check: recursor stats unavailable (no counter source)"
        failed=1
    else
        if (( rec_ce > RECURSOR_FLOOR_TOLERANCE )); then
            log_fail "Cache floor check: recursor record cache holds $rec_ce entries (tolerance $RECURSOR_FLOOR_TOLERANCE for background housekeeping)"
            failed=1
        elif (( rec_ce > 0 )); then
            log_warn "Cache floor check: recursor record cache holds $rec_ce housekeeping entr(y/ies) (security-status poll; within tolerance $RECURSOR_FLOOR_TOLERANCE)"
        fi
        if (( rec_pce > RECURSOR_FLOOR_TOLERANCE )); then
            log_fail "Cache floor check: recursor packet cache holds $rec_pce entries (tolerance $RECURSOR_FLOOR_TOLERANCE)"
            failed=1
        elif (( rec_pce > 0 )); then
            log_warn "Cache floor check: recursor packet cache holds $rec_pce housekeeping entr(y/ies) (within tolerance $RECURSOR_FLOOR_TOLERANCE)"
        fi
    fi

    if [[ $failed -eq 1 ]]; then
        return 1
    fi
    log_pass "Cache floor verified: dnsdist packet cache empty; recursor caches empty within housekeeping tolerance"
    return 0
}

# =============================================================================
# CLEARING PLAN + CLEARING (fail-closed, abort before dnsperf)
# =============================================================================

# print_clearing_plan <mode>: exactly what will be cleared and how.
print_clearing_plan() {
    local mode="$1"
    case "$mode" in
        console)
            cat << EOF
Clearing plan (clear-mode=console, non-disruptive):
  1. recursor record+packet+negative caches:
       docker exec $RECURSOR_CONTAINER rec_control --socket-dir=$RECURSOR_SOCKET_DIR wipe-cache '\$'
  2. dnsdist packet cache (default pool):
       docker exec $DNSDIST_CONTAINER dnsdist -c -C /tmp/dnsdist.conf \\
         -e "getPool(''):getCache():expunge(0)"
     (clearCache()/mvCacheToDownstream() do not exist in dnsdist 2.0.8;
      expunge(0) keeps 0 entries - verified against the 2.0.8 source)
  3. verify floor: dnsdist entries == 0 AND recursor cache-entries AND
     packetcache-entries within the housekeeping tolerance (background
     security-poll entries; verified from live counters, not tool exit codes)
  Prerequisite: DNSDIST_CONSOLE_KEY set in .env when the dnsdist container was
  created (entrypoint appends setKey()+controlSocket(127.0.0.1:5199)).
  Any failed or unverifiable step aborts the run BEFORE dnsperf.
EOF
            ;;
        restart)
            cat << EOF
Clearing plan (clear-mode=restart, DESTRUCTIVE - explicit opt-in):
  1. docker restart $DNSDIST_CONTAINER $RECURSOR_CONTAINER
     (drops all in-memory caches AND client connections)
  2. bounded wait (<= ${RESTART_HEALTH_TIMEOUT}s) for BOTH containers to report
     healthy BEFORE any pre-run counters are taken
  3. verify floor: dnsdist entries == 0 AND recursor cache-entries AND
     packetcache-entries within the housekeeping tolerance
  Only the dnsdist and recursor containers are ever restarted; any other
  --clear-mode value is refused (exit 3).
EOF
            ;;
        *)
            echo "Clearing plan: unrecognized clear-mode '$mode' - refusing to clear anything" >&2
            return 1
            ;;
    esac
}

# console_available: checks that the running dnsdist container has the console
# enabled (DNSDIST_CONSOLE_KEY in its environment, i.e. the entrypoint appended
# setKey to /tmp/dnsdist.conf). Fails closed with instructions.
console_available() {
    if ! container_running "$DNSDIST_CONTAINER"; then
        log_fail "dnsdist container '$DNSDIST_CONTAINER' is not running"
        return 1
    fi
    if [[ -z "$(docker exec "$DNSDIST_CONTAINER" printenv DNSDIST_CONSOLE_KEY 2>/dev/null)" ]]; then
        log_fail "DNSDIST_CONSOLE_KEY is not set on the dnsdist container - console clearing is unavailable"
        log_info "Fail-closed: refusing to run a 'cold' phase that would silently measure a warm cache"
        log_info "Fix: set DNSDIST_CONSOLE_KEY in .env (generate: head -c 32 /dev/urandom | base64 -w0)"
        log_info "     then recreate the container: docker compose up -d dnsdist"
        log_info "Or opt into destructive restart clearing: --clear-mode restart"
        return 1
    fi
    return 0
}

# clear_recursor_<mode>: return 0 only on verified success
clear_recursor_console() {
    local out rc
    if ! out=$(docker exec "$RECURSOR_CONTAINER" \
        rec_control --socket-dir="$RECURSOR_SOCKET_DIR" wipe-cache '$' 2>&1); then
        rc=$?
        log_fail "rec_control wipe-cache failed (rc=$rc): $out"
        return 1
    fi
    log_pass "recursor wipe-cache accepted: $(printf '%s' "$out" | head -1)"
    return 0
}

clear_dnsdist_console() {
    # NOTE: the dnsdist console client exits 0 even on auth failure, so the
    # numeric result line AND the subsequent floor verification are the real
    # success signals.
    local out
    if ! out=$(docker exec "$DNSDIST_CONTAINER" \
        dnsdist -c -C /tmp/dnsdist.conf \
        -e "getPool(''):getCache():expunge(0)" 2>&1); then
        log_fail "dnsdist console client failed: $(printf '%s' "$out" | tail -1)"
        return 1
    fi
    local result_line
    result_line=$(printf '%s' "$out" | tail -1)
    if ! [[ "$result_line" =~ ^[0-9]+$ ]]; then
        log_fail "dnsdist expunge(0) produced no numeric result (console unreachable or misconfigured): $result_line"
        return 1
    fi
    log_pass "dnsdist expunge(0) removed $result_line packet-cache entries"
    return 0
}

clear_dnsdist_restart() {
    log_warn "DESTRUCTIVE: docker restart $DNSDIST_CONTAINER (drops connections + cache)"
    if ! docker restart "$DNSDIST_CONTAINER" &>/dev/null; then
        log_fail "docker restart $DNSDIST_CONTAINER failed"
        return 1
    fi
    if ! wait_container_healthy "$DNSDIST_CONTAINER" "$RESTART_HEALTH_TIMEOUT"; then
        return 1
    fi
    log_pass "dnsdist restarted and healthy"
    return 0
}

clear_recursor_restart() {
    log_warn "DESTRUCTIVE: docker restart $RECURSOR_CONTAINER (drops connections + cache)"
    if ! docker restart "$RECURSOR_CONTAINER" &>/dev/null; then
        log_fail "docker restart $RECURSOR_CONTAINER failed"
        return 1
    fi
    if ! wait_container_healthy "$RECURSOR_CONTAINER" "$RESTART_HEALTH_TIMEOUT"; then
        return 1
    fi
    log_pass "recursor restarted and healthy"
    return 0
}

# do_clear: perform and VERIFY the full clearing sequence. Returns 1 (and
# prints the reason) on any failure - callers must abort before dnsperf.
do_clear() {
    log_section "Clearing Caches (clear-mode=$CLEAR_MODE)"

    print_clearing_plan "$CLEAR_MODE" || return 1

    if [[ "$CLEAR_MODE" == "console" ]]; then
        if ! console_available; then
            return 1
        fi
        if ! clear_recursor_console; then
            log_fail "ABORT: recursor cache clear failed - not running dnsperf on a partially cleared stack"
            return 1
        fi
        if ! clear_dnsdist_console; then
            log_fail "ABORT: dnsdist cache clear failed - not running dnsperf on a partially cleared stack"
            return 1
        fi
    elif [[ "$CLEAR_MODE" == "restart" ]]; then
        if ! clear_dnsdist_restart; then
            log_fail "ABORT: dnsdist restart failed - not running dnsperf"
            return 1
        fi
        if ! clear_recursor_restart; then
            log_fail "ABORT: recursor restart failed - not running dnsperf"
            return 1
        fi
    else
        log_fail "ABORT: unrecognized clear target '$CLEAR_MODE' - refusing to clear anything"
        return 1
    fi

    # Authoritative verification: live counters must show every layer empty.
    sleep 1  # let counters settle
    collect_stats
    if ! verify_cache_floor "$STATS_JSON"; then
        log_fail "ABORT: cache floor verification failed - not running dnsperf on a non-empty cache"
        return 1
    fi

    CLEAR_REPORT=$(jq -cn --arg mode "$CLEAR_MODE" \
        --arg dd "$STATS_DD_SOURCE" --arg rec "$STATS_REC_SOURCE" \
        '{mode: $mode, verified_empty: true,
          stats_sources: {dnsdist: $dd, recursor: $rec}}')
    return 0
}

CLEAR_REPORT="null"

# =============================================================================
# PRECACHE WARMING QUIESCE
# =============================================================================
# The admin-ui scheduler runs precache_warming every 5 minutes; the job re-reads
# settings.precache_enabled each time it fires. The harness pauses the job by
# flipping that setting to false via psql in the postgres container (the same
# mechanism the operations runbook uses for precache tuning) and restores the
# original value afterwards (also on abnormal exit, via the EXIT trap).
#
# The HTTP alternative (POST /precache/settings) was considered and rejected:
# it requires an authenticated admin session and rewrites every precache field
# (domain_count, refresh minutes, ...) with form defaults, so it is not safe
# for an unattended harness.

PRECACHE_STATE="not-paused"
PRECACHE_ORIGINAL=""

precache_pause() {
    PRECACHE_STATE="not-paused"
    if [[ "$PRECACHE_PAUSE" != "true" ]]; then
        PRECACHE_STATE="skipped-by-flag"
        log_info "Precache pause skipped (--no-precache-pause)"
        return 0
    fi
    if ! container_running "$POSTGRES_CONTAINER"; then
        if [[ "$STRICT_QUIESCE" == "true" ]]; then
            log_fail "strict-quiesce: postgres container '$POSTGRES_CONTAINER' is not running - cannot pause precache warming"
            return 1
        fi
        PRECACHE_STATE="unavailable:postgres-not-running"
        log_warn "Cannot pause precache warming ($POSTGRES_CONTAINER not running); proceeding without quiesce"
        log_warn "A warming job firing mid-measurement can skew cold/latency results"
        return 0
    fi
    local psql_cmd
    psql_cmd=(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c)
    # A missing row is NOT a read failure: fresh deployments never wrote the
    # row and the app default (precache_enabled=true) applies. Distinguish
    # absent from failure with a coalesce marker.
    local current
    if ! current=$("${psql_cmd[@]}" "SELECT coalesce((SELECT value FROM settings WHERE key='precache_enabled'), '__absent__')" 2>/dev/null) || [[ -z "$current" ]]; then
        if [[ "$STRICT_QUIESCE" == "true" ]]; then
            log_fail "strict-quiesce: cannot read settings.precache_enabled: ${current:-<empty>}"
            return 1
        fi
        PRECACHE_STATE="unavailable:settings-read-failed"
        log_warn "Cannot read settings.precache_enabled - proceeding without quiesce"
        return 0
    fi
    if [[ "$current" == "__absent__" ]]; then
        PRECACHE_ORIGINAL="absent"
    else
        PRECACHE_ORIGINAL="$current"
    fi
    if [[ "$PRECACHE_ORIGINAL" == "false" ]]; then
        PRECACHE_STATE="already-disabled"
        log_pass "Precache warming already disabled (settings.precache_enabled=false)"
        return 0
    fi
    # Upsert: absent rows have nothing to UPDATE (0-row UPDATE "succeeds"
    # while leaving warming on), so insert-or-update in one statement.
    if ! "${psql_cmd[@]}" "INSERT INTO settings (key, value, updated_at) VALUES ('precache_enabled', 'false', NOW()) ON CONFLICT (key) DO UPDATE SET value='false', updated_at=NOW()" &>/dev/null; then
        if [[ "$STRICT_QUIESCE" == "true" ]]; then
            log_fail "strict-quiesce: UPDATE settings.precache_enabled=false failed"
            return 1
        fi
        PRECACHE_STATE="unavailable:update-failed"
        log_warn "Failed to pause precache warming - proceeding without quiesce"
        return 0
    fi
    local readback
    readback=$("${psql_cmd[@]}" "SELECT value FROM settings WHERE key='precache_enabled'" 2>/dev/null)
    if [[ "$readback" != "false" ]]; then
        if [[ "$STRICT_QUIESCE" == "true" ]]; then
            log_fail "strict-quiesce: precache_enabled readback is '$readback' after update"
            return 1
        fi
        PRECACHE_STATE="unavailable:readback-mismatch"
        log_warn "precache_enabled did not flip to false (readback: '$readback') - proceeding without quiesce"
        return 0
    fi
    PRECACHE_STATE="paused"
    if [[ "$PRECACHE_ORIGINAL" == "absent" ]]; then
        log_pass "Precache warming paused (settings.precache_enabled: absent/default-true -> false; row removed on exit)"
    else
        log_pass "Precache warming paused (settings.precache_enabled: $PRECACHE_ORIGINAL -> false; restore on exit)"
    fi
    return 0
}

precache_resume() {
    if [[ "$PRECACHE_STATE" != "paused" ]]; then
        return 0
    fi
    local psql_cmd
    psql_cmd=(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c)
    # Symmetric restore: an absent original goes back to absent (the app
    # default re-applies); a stored original gets its value back.
    local restore_sql="UPDATE settings SET value='${PRECACHE_ORIGINAL}', updated_at=NOW() WHERE key='precache_enabled'"
    if [[ "$PRECACHE_ORIGINAL" == "absent" ]]; then
        restore_sql="DELETE FROM settings WHERE key='precache_enabled'"
    fi
    if "${psql_cmd[@]}" "$restore_sql" &>/dev/null; then
        local readback
        readback=$("${psql_cmd[@]}" "SELECT value FROM settings WHERE key='precache_enabled'" 2>/dev/null)
        if [[ "$readback" == "$PRECACHE_ORIGINAL" ]]; then
            log_pass "Precache warming restored (settings.precache_enabled=$PRECACHE_ORIGINAL)"
            PRECACHE_STATE="restored"
            return 0
        fi
    fi
    log_fail "Could not restore precache_enabled to '$PRECACHE_ORIGINAL' - MANUAL FIX REQUIRED:"
    log_fail "  docker exec $POSTGRES_CONTAINER psql -U $POSTGRES_USER -d $POSTGRES_DB -c \"UPDATE settings SET value='$PRECACHE_ORIGINAL' WHERE key='precache_enabled'\""
    PRECACHE_STATE="restore-failed"
    return 1
}

# =============================================================================
# COUNTER DELTAS (hit ratios from pre/post snapshots, per layer)
# =============================================================================

# compute_layer_deltas <pre_json> <post_json>: per-layer counter deltas +
# hit ratios (percent). Layers with null stats yield null ratios.
compute_layer_deltas() {
    local pre="$1" post="$2"
    jq -cn --argjson pre "$pre" --argjson post "$post" '
    def layer($a; $b):
        if ($a == null or $b == null) then {hits: null, misses: null, total: null, hit_ratio_pct: null}
        else
            {hits: ($b.hits - $a.hits), misses: ($b.misses - $a.misses)} |
            .total = (.hits + .misses) |
            .hit_ratio_pct = (if .total > 0 then ((.hits * 1000 / .total) | round / 10) else null end)
        end;
    {
        dnsdist:            layer($pre.dnsdist; $post.dnsdist),
        recursor_packetcache: layer(
            (if $pre.recursor == null then null else {hits: $pre.recursor.packetcache_hits, misses: $pre.recursor.packetcache_misses} end);
            (if $post.recursor == null then null else {hits: $post.recursor.packetcache_hits, misses: $post.recursor.packetcache_misses} end)),
        recursor_recordcache: layer(
            (if $pre.recursor == null then null else {hits: $pre.recursor.cache_hits, misses: $pre.recursor.cache_misses} end);
            (if $post.recursor == null then null else {hits: $post.recursor.cache_hits, misses: $post.recursor.cache_misses} end))
    }'
}

# ratio_gate <ratio_pct|null> <min_pct> <layer>: fails closed when a measured
# layer's ratio is below its target (null ratio = unmeasured = failure).
ratio_gate() {
    local ratio="$1" min="$2" layer="$3"
    if [[ "$ratio" == "null" || -z "$ratio" ]]; then
        log_fail "$layer hit ratio unmeasurable (counter source missing) - gating as failure"
        return 1
    fi
    if (( $(echo "$ratio < $min" | bc -l 2>/dev/null || echo 1) )); then
        log_fail "$layer hit ratio ${ratio}% below target ${min}%"
        return 1
    fi
    log_pass "$layer hit ratio ${ratio}% >= ${min}%"
    return 0
}

# latency_gate <value_ms> <limit_ms> <label>: true failure when over limit.
latency_gate() {
    local value="$1" limit="$2" label="$3"
    if [[ "$value" == "null" || -z "$value" ]]; then
        log_fail "$label latency unmeasurable - gating as failure"
        return 1
    fi
    if (( $(echo "$value > $limit" | bc -l 2>/dev/null || echo 1) )); then
        log_fail "$label latency (${value}ms) exceeds threshold (${limit}ms)"
        return 1
    fi
    log_pass "$label latency ${value}ms <= ${limit}ms"
    return 0
}

# =============================================================================
# DNSPERF EXECUTION AND PARSING (fail loudly on unknown output)
# =============================================================================

# run_dnsperf <target> <port> <corpus> <duration> <qps> <output_file>
# Always runs with -O latency-histogram (version-gated >= 2.14.0 in
# prerequisites). dnsperf has no JSON output; we parse the text format.
run_dnsperf() {
    local target="$1"
    local port="$2"
    local corpus="$3"
    local duration="$4"
    local qps="$5"
    local output_file="$6"

    dnsperf -s "$target" -p "$port" \
        -d "$corpus" \
        -l "$duration" \
        -Q "$qps" \
        -m udp \
        -O latency-histogram \
        > "$output_file" 2>&1
}

# parse_dnsperf_output <file>: validates the KNOWN dnsperf text format and
# computes percentiles from the latency histogram. Sets DNSPERF_PARSED (JSON).
# Fails loudly (rc 1 + message) on unknown/missing output - never returns
# null percentiles.
#
# Verified format (dnsperf 2.14.0/2.16.0):
#   Queries sent:         250
#   Queries completed:    250 (100.00%)
#   Queries lost:         0 (0.00%)
#   Run time (s):         5.000159
#   Queries per second:   49.998410
#   Average Latency (s):  0.000396 (min 0.000064, max 0.027971)
#   Latency StdDev (s):   0.002314
#   Latency bucket (s):   answer count
#   0.000082 - 0.000083:  1
# Latency values are SECONDS; converted to milliseconds here.
# Percentiles use the bucket UPPER bound (conservative for gating).
parse_dnsperf_output() {
    local file="$1"
    DNSPERF_PARSED=""

    if [[ ! -s "$file" ]]; then
        log_fail "dnsperf output is empty or missing: $file"
        return 1
    fi

    if ! grep -q "DNS Performance Testing Tool" "$file"; then
        log_fail "dnsperf output does not look like dnsperf text output (missing banner): $file"
        log_info "Failing loudly instead of nulling percentiles - unknown output format"
        return 1
    fi

    local sent completed lost run_time qps avg_lat min_lat max_lat stddev
    sent=$(grep -oE 'Queries sent:[[:space:]]+[0-9]+' "$file" | grep -oE '[0-9]+' | head -1)
    completed=$(grep -oE 'Queries completed:[[:space:]]+[0-9]+' "$file" | grep -oE '[0-9]+' | head -1)
    lost=$(grep -oE 'Queries lost:[[:space:]]+[0-9]+' "$file" | grep -oE '[0-9]+' | head -1)
    run_time=$(grep -oE 'Run time \(s\):[[:space:]]+[0-9.]+' "$file" | grep -oE '[0-9.]+' | head -1)
    qps=$(grep -oE 'Queries per second:[[:space:]]+[0-9.]+' "$file" | grep -oE '[0-9.]+' | head -1)
    avg_lat=$(grep -oE 'Average Latency \(s\):[[:space:]]+[0-9.]+' "$file" | grep -oE '[0-9.]+' | head -1)
    min_lat=$(grep -oE '\(min [0-9.]+, max [0-9.]+' "$file" | grep -oE '[0-9.]+' | head -1)
    max_lat=$(grep -oE '\(min [0-9.]+, max [0-9.]+' "$file" | grep -oE '[0-9.]+' | tail -1)
    stddev=$(grep -oE 'Latency StdDev \(s\):[[:space:]]+[0-9.]+' "$file" | grep -oE '[0-9.]+' | head -1)

    local missing=()
    local f
    for f in sent:"Queries sent" completed:"Queries completed" lost:"Queries lost" \
             run_time:"Run time" qps:"Queries per second" avg_lat:"Average Latency"; do
        local var="${f%%:*}" marker="${f#*:}"
        if [[ -z "${!var}" ]]; then
            missing+=("$marker")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_fail "dnsperf output is missing required fields: ${missing[*]} - unknown output format, failing loudly"
        return 1
    fi

    # Percentiles from the latency histogram buckets (upper bound, ms).
    local p50 p95 p99 bucket_total
    read -r p50 p95 p99 bucket_total <<< "$(awk '
        /^[[:space:]]*[0-9]+\.[0-9]+ - [0-9]+\.[0-9]+:[[:space:]]*[0-9]+$/ {
            lo = $1 + 0; hi = $3 + 0; n = $NF + 0
            total += n
            buckets[++count] = lo; buckets_hi[count] = hi; buckets_n[count] = n
        }
        END {
            if (total == 0) { print "null null null 0"; exit }
            split("50 95 99", P, " ")
            out = ""
            for (pi = 1; pi <= 3; pi++) {
                rank = total * P[pi] / 100
                cum = 0; val = ""
                for (i = 1; i <= count; i++) {
                    cum += buckets_n[i]
                    if (cum >= rank && rank > 0) { val = buckets_hi[i] * 1000; break }
                }
                if (val == "") { val = buckets_hi[count] * 1000 }
                out = out (pi > 1 ? " " : "") sprintf("%.3f", val)
            }
            print out, total
        }' "$file")"

    if [[ "$bucket_total" == "0" || -z "$bucket_total" ]]; then
        log_fail "dnsperf produced no latency histogram (queries_completed=${completed})"
        log_info "dnsperf >= ${DNSPERF_MIN_VERSION} prints buckets with -O latency-histogram;"
        log_info "no buckets usually means a build without Concurrency Kit histograms, or zero completed queries"
        return 1
    fi

    if (( completed != bucket_total )); then
        log_warn "Histogram total (${bucket_total}) != Queries completed (${completed}); using histogram-derived percentiles"
    fi

    DNSPERF_PARSED=$(jq -n \
        --argjson queries_sent "$sent" \
        --argjson queries_completed "$completed" \
        --argjson queries_lost "$lost" \
        --argjson run_time "$run_time" \
        --argjson qps_actual "$qps" \
        --argjson avg_latency_ms "$(awk -v v="$avg_lat" 'BEGIN{printf "%.3f", v*1000}')" \
        --argjson min_latency_ms "$(awk -v v="$min_lat" 'BEGIN{printf "%.3f", v*1000}')" \
        --argjson max_latency_ms "$(awk -v v="$max_lat" 'BEGIN{printf "%.3f", v*1000}')" \
        --argjson stddev_ms "$(awk -v v="$stddev" 'BEGIN{printf "%.3f", v*1000}')" \
        --argjson p50 "$p50" --argjson p95 "$p95" --argjson p99 "$p99" \
        --argjson histogram_samples "$bucket_total" \
        '{
            queries_sent: $queries_sent,
            queries_completed: $queries_completed,
            queries_lost: $queries_lost,
            run_time_s: $run_time,
            qps_actual: $qps_actual,
            avg_latency_ms: $avg_latency_ms,
            min_latency_ms: $min_latency_ms,
            max_latency_ms: $max_latency_ms,
            stddev_ms: $stddev_ms,
            p50_latency_ms: $p50,
            p95_latency_ms: $p95,
            p99_latency_ms: $p99,
            histogram_samples: $histogram_samples,
            percentile_method: "dnsperf -O latency-histogram buckets, bucket upper bound (ms)"
        }')
    return 0
}

DNSPERF_PARSED=""

# =============================================================================
# BASELINE CAPTURE (per-layer occupancy, memory, threads, pipeline health)
# =============================================================================

capture_baseline() {
    # Occupancy vs capacity per layer (from a fresh stats snapshot).
    local occupancy
    occupancy=$(jq -c '
        {
            dnsdist_packetcache: (if .dnsdist == null then null else
                {entries: .dnsdist.entries, capacity: .dnsdist.maxEntries,
                 utilization_pct: (if .dnsdist.maxEntries > 0 then ((.dnsdist.entries * 1000 / .dnsdist.maxEntries) | round / 10) else null end)} end),
            recursor_recordcache: (if .recursor == null then null else
                {entries: .recursor.cache_entries, capacity: .recursor.max_cache_entries,
                 utilization_pct: (if .recursor.max_cache_entries > 0 then ((.recursor.cache_entries * 1000 / .recursor.max_cache_entries) | round / 10) else null end)} end),
            recursor_packetcache: (if .recursor == null then null else
                {entries: .recursor.packetcache_entries, capacity: .recursor.max_packetcache_entries,
                 utilization_pct: (if .recursor.max_packetcache_entries > 0 then ((.recursor.packetcache_entries * 1000 / .recursor.max_packetcache_entries) | round / 10) else null end)} end)
        }' <<< "$STATS_JSON" 2>/dev/null) || occupancy="null"

    # Container RSS / CPU (all powerblockade-* containers that exist).
    local containers
    containers=$(docker stats --no-stream --format '{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}' 2>/dev/null | grep '^powerblockade-' || true)

    # Host memory + swap.
    local mem_avail swap_free swap_total pswpin pswpout
    mem_avail=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null)
    swap_free=$(awk '/^SwapFree:/ {print $2}' /proc/meminfo 2>/dev/null)
    swap_total=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo 2>/dev/null)
    pswpin=$(awk '/^pswpin/ {print $2}' /proc/vmstat 2>/dev/null)
    pswpout=$(awk '/^pswpout/ {print $2}' /proc/vmstat 2>/dev/null)

    # Per-thread distribution where available: recursor cpu-msec-thread-*.
    local threads="{}"
    if [[ -n "$STATS_REC_SOURCE" ]]; then
        threads=$(docker exec "$RECURSOR_CONTAINER" \
            rec_control --socket-dir="$RECURSOR_SOCKET_DIR" get-all 2>/dev/null \
            | awk '/^cpu-msec-thread-/ {gsub("-", "_", $1); v[$1] = $2}
                   END {printf "{"; sep=""; for (k in v) {printf "%s\"%s\": %s", sep, k, v[k]; sep=", "}; printf "}"}')
        [[ -n "$threads" ]] || threads="{}"
    fi

    # dnstap-processor health: metrics endpoint via docker exec (the port is
    # expose-only on the compose network; curl from the host cannot reach it).
    local dnstap="unavailable"
    if container_running "$DNSTAP_CONTAINER"; then
        local code
        code=$(docker exec "$DNSTAP_CONTAINER" sh -c \
            'if command -v curl >/dev/null 2>&1; then curl -so /dev/null -w "%{http_code}" -m 5 http://127.0.0.1:9422/metrics; elif command -v wget >/dev/null 2>&1; then wget -q -O /dev/null -T 5 http://127.0.0.1:9422/metrics && echo 200; else echo no-http-client; fi' 2>/dev/null || echo exec-failed)
        case "$code" in
            200) dnstap="healthy" ;;
            *) dnstap="unhealthy:http-$code" ;;
        esac
    fi

    BASELINE_JSON=$(jq -cn \
        --argjson occupancy "$occupancy" \
        --arg containers "$containers" \
        --arg mem_avail "${mem_avail:-unknown}" \
        --arg swap_free "${swap_free:-unknown}" \
        --arg swap_total "${swap_total:-unknown}" \
        --arg pswpin "${pswpin:-unknown}" \
        --arg pswpout "${pswpout:-unknown}" \
        --argjson threads "$threads" \
        --arg dnstap "$dnstap" \
        --arg dd_src "$STATS_DD_SOURCE" --arg rec_src "$STATS_REC_SOURCE" '
        {
            cache_occupancy: $occupancy,
            containers: (if $containers == "" then [] else
                [$containers | split("\n")[] | split("|") | {name: .[0], mem_usage: .[1], cpu_pct: .[2]}] end),
            host_memory: {
                mem_available_kb: (try ($mem_avail | tonumber) catch null),
                swap_free_kb: (try ($swap_free | tonumber) catch null),
                swap_total_kb: (try ($swap_total | tonumber) catch null),
                pswpin_pages: (try ($pswpin | tonumber) catch null),
                pswpout_pages: (try ($pswpout | tonumber) catch null)
            },
            recursor_threads_cpu_msec: $threads,
            dnstap_processor: $dnstap,
            stats_sources: {dnsdist: (if $dd_src == "" then null else $dd_src end),
                            recursor: (if $rec_src == "" then null else $rec_src end)}
        }')
}

BASELINE_JSON="null"

# =============================================================================
# BENCHMARK PHASE IMPLEMENTATIONS
# =============================================================================

# run_measurement_dnsperf <label> <qps> <duration> <outfile>: executes dnsperf
# and parses; on execution OR parse failure marks the phase failed loudly and
# aborts the remaining phases. Returns 1 on failure.
run_measurement_dnsperf() {
    local label="$1" qps="$2" duration="$3" outfile="$4"
    if ! run_dnsperf "$TARGET" "$PORT" "$CORPUS" "$duration" "$qps" "$outfile"; then
        log_fail "$label: dnsperf execution failed (see $outfile)"
        return 1
    fi
    if ! parse_dnsperf_output "$outfile"; then
        log_fail "$label: dnsperf output could not be parsed - failing loudly, aborting remaining phases"
        ABORT_REMAINING_PHASES=true
        return 1
    fi
    return 0
}

run_cold_cache_phase() {
    log_section "Phase 1: Cold Cache Benchmark"

    local passed=true
    local regressions=()

    # Step 1: clear BOTH layers (fail-closed: abort before dnsperf)
    if ! do_clear; then
        CLEAR_FAILED=true
        COLD_CACHE_RESULT=$(jq -n --argjson clear "$CLEAR_REPORT" \
            '{implemented: true, passed: false, error: "cache_clear_failed", clear: $clear}')
        PHASES_RUN=$((PHASES_RUN + 1))
        PHASES_FAILED=$((PHASES_FAILED + 1))
        push_regression "cold_cache: cache_clear_failed"
        ABORT_REMAINING_PHASES=true
        return $EXIT_PHASE_FAILED
    fi

    # Step 2: snapshot pre-run counters (after verified clear)
    local pre_stats="$STATS_JSON"

    # Step 3: run dnsperf
    local dnsperf_output="${RESULTS_DIR}/cold-cache-raw-$$.txt"
    log_info "Running dnsperf for ${DURATION}s at 1000 QPS..."
    if ! run_measurement_dnsperf "cold" 1000 "$DURATION" "$dnsperf_output"; then
        COLD_CACHE_RESULT=$(jq -n --argjson clear "$CLEAR_REPORT" \
            '{implemented: true, passed: false, error: "dnsperf_failed", clear: $clear}')
        PHASES_RUN=$((PHASES_RUN + 1))
        PHASES_FAILED=$((PHASES_FAILED + 1))
        push_regression "cold_cache: dnsperf_failed"
        rm -f "$dnsperf_output" 2>/dev/null
        return $EXIT_PHASE_FAILED
    fi

    # Step 4: post-run counters and per-layer deltas
    collect_stats
    local deltas
    deltas=$(compute_layer_deltas "$pre_stats" "$STATS_JSON")

    # Step 5: evaluate latency thresholds (p50/p95/p99)
    local p50 p95 p99
    p50=$(jq -r '.p50_latency_ms' <<< "$DNSPERF_PARSED")
    p95=$(jq -r '.p95_latency_ms' <<< "$DNSPERF_PARSED")
    p99=$(jq -r '.p99_latency_ms' <<< "$DNSPERF_PARSED")
    latency_gate "$p50" "$COLD_P50_THRESHOLD" "cold p50" || { passed=false; regressions+=("p50_latency_exceeded"); }
    latency_gate "$p95" "$COLD_P95_THRESHOLD" "cold p95" || { passed=false; regressions+=("p95_latency_exceeded"); }
    latency_gate "$p99" "$COLD_P99_THRESHOLD" "cold p99" || { passed=false; regressions+=("p99_latency_exceeded"); }

    # Step 6: build result JSON
    local success_rate
    success_rate=$(jq -r 'if .queries_sent > 0 then ((.queries_completed * 1000 / .queries_sent) | round / 10) else 0 end' <<< "$DNSPERF_PARSED")
    local reg_array
    reg_array=$(json_array_from_list ${regressions[@]+"${regressions[@]}"})

    COLD_CACHE_RESULT=$(jq -n \
        --argjson implemented true \
        --argjson passed "$passed" \
        --argjson metrics "$DNSPERF_PARSED" \
        --argjson deltas "$deltas" \
        --argjson success_rate "$success_rate" \
        --argjson p50_limit "$COLD_P50_THRESHOLD" \
        --argjson p95_limit "$COLD_P95_THRESHOLD" \
        --argjson p99_limit "$COLD_P99_THRESHOLD" \
        --argjson clear "$CLEAR_REPORT" \
        --argjson reg "$reg_array" \
        '{
            implemented: $implemented,
            passed: $passed,
            metrics: ($metrics + {success_rate_pct: $success_rate}),
            counter_deltas: $deltas,
            thresholds: {p50_limit_ms: $p50_limit, p95_limit_ms: $p95_limit, p99_limit_ms: $p99_limit},
            clear: $clear,
            regressions: $reg
        }')

    PHASES_RUN=$((PHASES_RUN + 1))
    if [[ "$passed" == "true" ]]; then
        log_pass "Cold cache phase passed"
        PHASES_PASSED=$((PHASES_PASSED + 1))
    else
        log_fail "Cold cache phase failed"
        PHASES_FAILED=$((PHASES_FAILED + 1))
        push_regression "cold_cache"
    fi

    rm -f "$dnsperf_output" 2>/dev/null
    [[ "$passed" == "true" ]] && return 0 || return $EXIT_PHASE_FAILED
}

run_warm_cache_phase() {
    log_section "Phase 2: Warm Cache Benchmark"

    local passed=true
    local regressions=()

    # Step 1: warmup - run corpus 3x to prime the cache
    log_info "Priming cache with 3x warmup runs..."
    local i
    for i in 1 2 3; do
        run_dnsperf "$TARGET" "$PORT" "$CORPUS" 30 500 "/dev/null" 2>/dev/null || true
        sleep 1
    done

    # Step 2: snapshot pre-run counters
    collect_stats
    local pre_stats="$STATS_JSON"

    # Step 3: run dnsperf at higher QPS
    local dnsperf_output="${RESULTS_DIR}/warm-cache-raw-$$.txt"
    log_info "Running dnsperf for ${DURATION}s at 5000 QPS..."
    if ! run_measurement_dnsperf "warm" 5000 "$DURATION" "$dnsperf_output"; then
        WARM_CACHE_RESULT=$(jq -n '{implemented: true, passed: false, error: "dnsperf_failed"}')
        PHASES_RUN=$((PHASES_RUN + 1))
        PHASES_FAILED=$((PHASES_FAILED + 1))
        push_regression "warm_cache: dnsperf_failed"
        rm -f "$dnsperf_output" 2>/dev/null
        return $EXIT_PHASE_FAILED
    fi

    # Step 4: post-run counters and per-layer DELTA hit ratios
    collect_stats
    local deltas
    deltas=$(compute_layer_deltas "$pre_stats" "$STATS_JSON")

    local p50 p95 p99
    p50=$(jq -r '.p50_latency_ms' <<< "$DNSPERF_PARSED")
    p95=$(jq -r '.p95_latency_ms' <<< "$DNSPERF_PARSED")
    p99=$(jq -r '.p99_latency_ms' <<< "$DNSPERF_PARSED")
    latency_gate "$p50" "$WARM_P50_THRESHOLD" "warm p50" || { passed=false; regressions+=("p50_latency_exceeded"); }
    latency_gate "$p95" "$WARM_P95_THRESHOLD" "warm p95" || { passed=false; regressions+=("p95_latency_exceeded"); }
    latency_gate "$p99" "$WARM_P99_THRESHOLD" "warm p99" || { passed=false; regressions+=("p99_latency_exceeded"); }

    # Gate on the dnsdist packet-cache delta ratio (the layer the warm phase
    # is supposed to exercise). Other layers are reported, not gated.
    local dd_ratio
    dd_ratio=$(jq -r '.dnsdist.hit_ratio_pct' <<< "$deltas")
    ratio_gate "$dd_ratio" "$WARM_CACHE_HIT_THRESHOLD" "warm dnsdist packet cache" \
        || { passed=false; regressions+=("cache_hit_ratio_low"); }

    local success_rate
    success_rate=$(jq -r 'if .queries_sent > 0 then ((.queries_completed * 1000 / .queries_sent) | round / 10) else 0 end' <<< "$DNSPERF_PARSED")
    local reg_array
    reg_array=$(json_array_from_list ${regressions[@]+"${regressions[@]}"})

    WARM_CACHE_RESULT=$(jq -n \
        --argjson implemented true \
        --argjson passed "$passed" \
        --argjson metrics "$DNSPERF_PARSED" \
        --argjson deltas "$deltas" \
        --argjson success_rate "$success_rate" \
        --argjson p50_limit "$WARM_P50_THRESHOLD" \
        --argjson p95_limit "$WARM_P95_THRESHOLD" \
        --argjson p99_limit "$WARM_P99_THRESHOLD" \
        --argjson hit_limit "$WARM_CACHE_HIT_THRESHOLD" \
        --argjson reg "$reg_array" \
        '{
            implemented: $implemented,
            passed: $passed,
            metrics: ($metrics + {success_rate_pct: $success_rate}),
            counter_deltas: $deltas,
            thresholds: {
                p50_limit_ms: $p50_limit, p95_limit_ms: $p95_limit, p99_limit_ms: $p99_limit,
                cache_hit_limit_pct: $hit_limit
            },
            regressions: $reg
        }')

    PHASES_RUN=$((PHASES_RUN + 1))
    if [[ "$passed" == "true" ]]; then
        log_pass "Warm cache phase passed"
        PHASES_PASSED=$((PHASES_PASSED + 1))
    else
        log_fail "Warm cache phase failed"
        PHASES_FAILED=$((PHASES_FAILED + 1))
        push_regression "warm_cache"
    fi

    rm -f "$dnsperf_output" 2>/dev/null
    [[ "$passed" == "true" ]] && return 0 || return $EXIT_PHASE_FAILED
}

run_saturation_phase() {
    log_section "Phase 3: Saturation Benchmark"

    local passed=true
    local regressions=()
    local saturation_duration=$((DURATION * 2))

    # Saturation uses a sustained dnsperf run. resperf was removed: its text
    # output could not be parsed from a verified format (the old code grepped
    # for markers that do not exist and silently fell back).
    local dnsperf_output="${RESULTS_DIR}/saturation-raw-$$.txt"
    log_info "Running dnsperf for ${saturation_duration}s at 10000 QPS (sustained saturation)..."

    if ! run_measurement_dnsperf "saturation" 10000 "$saturation_duration" "$dnsperf_output"; then
        SATURATION_RESULT=$(jq -n '{implemented: true, passed: false, error: "benchmark_execution_failed"}')
        PHASES_RUN=$((PHASES_RUN + 1))
        PHASES_FAILED=$((PHASES_FAILED + 1))
        push_regression "saturation: execution_failed"
        rm -f "$dnsperf_output" 2>/dev/null
        return $EXIT_PHASE_FAILED
    fi

    local max_sustained error_rate latency_at_50 queries_sent queries_lost
    max_sustained=$(jq -r '.qps_actual' <<< "$DNSPERF_PARSED")
    latency_at_50=$(jq -r '.p50_latency_ms' <<< "$DNSPERF_PARSED")
    queries_sent=$(jq -r '.queries_sent' <<< "$DNSPERF_PARSED")
    queries_lost=$(jq -r '.queries_lost' <<< "$DNSPERF_PARSED")
    error_rate=$(awk -v l="$queries_lost" -v s="$queries_sent" \
        'BEGIN { if (s > 0) printf "%.2f", l * 100 / s; else print 0 }')

    if (( $(echo "$max_sustained < $SATURATION_MIN_QPS" | bc -l 2>/dev/null || echo 0) )); then
        log_fail "Max sustained QPS (${max_sustained}) below threshold (${SATURATION_MIN_QPS})"
        passed=false
        regressions+=("qps_below_threshold")
    else
        log_pass "Sustained QPS ${max_sustained} >= ${SATURATION_MIN_QPS}"
    fi

    if (( $(echo "$error_rate > 5" | bc -l 2>/dev/null || echo 0) )); then
        log_fail "Error rate (${error_rate}%) exceeds 5% threshold"
        passed=false
        regressions+=("error_rate_high")
    else
        log_pass "Error rate ${error_rate}% <= 5%"
    fi

    local reg_array
    reg_array=$(json_array_from_list ${regressions[@]+"${regressions[@]}"})

    SATURATION_RESULT=$(jq -n \
        --argjson implemented true \
        --argjson passed "$passed" \
        --argjson metrics "$DNSPERF_PARSED" \
        --argjson max_qps "$max_sustained" \
        --argjson error_rate "$error_rate" \
        --argjson latency_at_50 "$latency_at_50" \
        --argjson duration "$saturation_duration" \
        --argjson min_qps "$SATURATION_MIN_QPS" \
        --argjson reg "$reg_array" \
        '{
            implemented: $implemented,
            passed: $passed,
            method: "dnsperf-sustained",
            metrics: ($metrics + {
                max_qps_sustained: $max_qps,
                latency_at_50pct_ms: $latency_at_50,
                error_rate_pct: $error_rate,
                duration_seconds: $duration
            }),
            thresholds: {min_qps: $min_qps},
            regressions: $reg
        }')

    PHASES_RUN=$((PHASES_RUN + 1))
    if [[ "$passed" == "true" ]]; then
        log_pass "Saturation phase passed"
        PHASES_PASSED=$((PHASES_PASSED + 1))
    else
        log_fail "Saturation phase failed"
        PHASES_FAILED=$((PHASES_FAILED + 1))
        push_regression "saturation"
    fi

    rm -f "$dnsperf_output" 2>/dev/null
    [[ "$passed" == "true" ]] && return 0 || return $EXIT_PHASE_FAILED
}

# run_ttw_phase: time-to-warm measurement.
#   1. Clear both layers (fail-closed) and snapshot the start time.
#   2. Drive continuous dnsperf load at TTW_QPS in windows of
#      TTW_WINDOW_SECONDS seconds.
#   3. A window PASSES when its dnsperf p99 <= DNS53_TTW_P99_THRESHOLD_MS and
#      every layer's window hit-ratio delta is >= its target.
#   4. The stack counts as warm after TTW_WINDOWS consecutive passing windows;
#      time-to-warm is the elapsed wall-clock time from the clear until the end
#      of the final window of that streak.
#   5. If no streak forms within TTW_MAX_WINDOWS windows, the phase fails.
run_ttw_phase() {
    log_section "Phase 4: Time-to-Warm"

    local streak=0 window=0 warmed=false warmed_at_elapsed=""
    local windows_json="[]"

    log_info "Warm criteria: ${TTW_WINDOWS} consecutive windows of ${TTW_WINDOW_SECONDS}s"
    log_info "  p99 <= ${TTW_P99_THRESHOLD}ms AND dnsdist >= ${TTW_DNSDIST_HIT_PCT}% AND packetcache >= ${TTW_PACKETCACHE_HIT_PCT}% AND recordcache >= ${TTW_RECCACHE_HIT_PCT}%"

    if ! do_clear; then
        CLEAR_FAILED=true
        TTW_RESULT=$(jq -n --argjson clear "$CLEAR_REPORT" \
            '{implemented: true, passed: false, error: "cache_clear_failed", clear: $clear}')
        PHASES_RUN=$((PHASES_RUN + 1))
        PHASES_FAILED=$((PHASES_FAILED + 1))
        push_regression "time_to_warm: cache_clear_failed"
        ABORT_REMAINING_PHASES=true
        return $EXIT_PHASE_FAILED
    fi

    local clear_epoch
    clear_epoch=$(date +%s)

    local window_pre="$STATS_JSON"
    local dnsperf_output="${RESULTS_DIR}/ttw-window-raw-$$.txt"

    while (( window < TTW_MAX_WINDOWS )); do
        window=$((window + 1))
        log_info "Window ${window}/${TTW_MAX_WINDOWS} (streak: ${streak}/${TTW_WINDOWS}) - ${TTW_WINDOW_SECONDS}s at ${TTW_QPS} QPS..."

        if ! run_measurement_dnsperf "time-to-warm window ${window}" "$TTW_QPS" "$TTW_WINDOW_SECONDS" "$dnsperf_output"; then
            TTW_RESULT=$(jq -n '{implemented: true, passed: false, error: "dnsperf_failed"}')
            PHASES_RUN=$((PHASES_RUN + 1))
            PHASES_FAILED=$((PHASES_FAILED + 1))
            push_regression "time_to_warm: dnsperf_failed"
            rm -f "$dnsperf_output" 2>/dev/null
            return $EXIT_PHASE_FAILED
        fi

        collect_stats
        local deltas
        deltas=$(compute_layer_deltas "$window_pre" "$STATS_JSON")
        window_pre="$STATS_JSON"

        local p99 dd_ratio pc_ratio rc_ratio elapsed
        p99=$(jq -r '.p99_latency_ms' <<< "$DNSPERF_PARSED")
        dd_ratio=$(jq -r '.dnsdist.hit_ratio_pct' <<< "$deltas")
        pc_ratio=$(jq -r '.recursor_packetcache.hit_ratio_pct' <<< "$deltas")
        rc_ratio=$(jq -r '.recursor_recordcache.hit_ratio_pct' <<< "$deltas")
        elapsed=$(( $(date +%s) - clear_epoch ))

        local window_ok=true window_failures=""
        if ! latency_gate "$p99" "$TTW_P99_THRESHOLD" "window ${window} p99"; then
            window_ok=false; window_failures+="p99_exceeded "
        fi
        if ! ratio_gate "$dd_ratio" "$TTW_DNSDIST_HIT_PCT" "window ${window} dnsdist hit"; then
            window_ok=false; window_failures+="dnsdist_ratio_low "
        fi
        if ! ratio_gate "$pc_ratio" "$TTW_PACKETCACHE_HIT_PCT" "window ${window} packetcache hit"; then
            window_ok=false; window_failures+="packetcache_ratio_low "
        fi
        if ! ratio_gate "$rc_ratio" "$TTW_RECCACHE_HIT_PCT" "window ${window} recordcache hit"; then
            window_ok=false; window_failures+="recordcache_ratio_low "
        fi

        windows_json=$(jq -c --argjson w "$windows_json" --argjson n "$window" \
            --argjson p99 "$p99" --argjson dd "$dd_ratio" --argjson pc "$pc_ratio" \
            --argjson rc "$rc_ratio" --argjson elapsed "$elapsed" \
            --arg ok "$window_ok" --arg failures "${window_failures:- }" \
            '$w + [{window: $n, passed: $ok, p99_latency_ms: $p99,
                     dnsdist_hit_pct: $dd, packetcache_hit_pct: $pc,
                     recordcache_hit_pct: $rc, elapsed_s: $elapsed,
                     failures: ($failures | split(" ") | map(select(length > 0)))}]')

        if [[ "$window_ok" == "true" ]]; then
            streak=$((streak + 1))
            if (( streak >= TTW_WINDOWS )); then
                warmed=true
                warmed_at_elapsed="$elapsed"
                log_pass "Warm state reached after ${elapsed}s (${streak} consecutive passing windows)"
                break
            fi
        else
            streak=0
        fi
    done

    rm -f "$dnsperf_output" 2>/dev/null

    local passed="false"
    if [[ "$warmed" == "true" ]]; then
        passed="true"
        log_pass "Time-to-warm: ${warmed_at_elapsed}s (criteria held for ${TTW_WINDOWS} consecutive ${TTW_WINDOW_SECONDS}s windows)"
    else
        log_fail "Time-to-warm: stack did not reach warm state within ${TTW_MAX_WINDOWS} windows"
    fi

    TTW_RESULT=$(jq -n \
        --argjson implemented true \
        --argjson passed "$passed" \
        --argjson windows "$windows_json" \
        --argjson windows_run "$window" \
        --argjson required_streak "$TTW_WINDOWS" \
        --argjson window_seconds "$TTW_WINDOW_SECONDS" \
        --argjson qps "$TTW_QPS" \
        --argjson time_to_warm_s "${warmed_at_elapsed:-null}" \
        --argjson clear "$CLEAR_REPORT" \
        --argjson p99_limit "$TTW_P99_THRESHOLD" \
        --argjson dd_min "$TTW_DNSDIST_HIT_PCT" \
        --argjson pc_min "$TTW_PACKETCACHE_HIT_PCT" \
        --argjson rc_min "$TTW_RECCACHE_HIT_PCT" \
        '{
            implemented: $implemented,
            passed: $passed,
            metrics: {
                time_to_warm_s: $time_to_warm_s,
                windows_run: $windows_run,
                required_consecutive_windows: $required_streak,
                window_seconds: $window_seconds,
                load_qps: $qps
            },
            thresholds: {
                p99_limit_ms: $p99_limit,
                dnsdist_hit_min_pct: $dd_min,
                packetcache_hit_min_pct: $pc_min,
                recordcache_hit_min_pct: $rc_min
            },
            windows: $windows,
            clear: $clear,
            definition: ("warm = p99 <= " + ($p99_limit | tostring) + "ms AND all layer window hit ratios at target for " + ($required_streak | tostring) + " consecutive " + ($window_seconds | tostring) + "s windows")
        }')

    PHASES_RUN=$((PHASES_RUN + 1))
    if [[ "$passed" == "true" ]]; then
        PHASES_PASSED=$((PHASES_PASSED + 1))
        return 0
    fi
    PHASES_FAILED=$((PHASES_FAILED + 1))
    push_regression "time_to_warm"
    return $EXIT_PHASE_FAILED
}

# =============================================================================
# OUTPUT GENERATION (Contract)
# =============================================================================

generate_json_output() {
    local benchmark_id
    benchmark_id="bm-$(date +%Y%m%d-%H%M%S)"
    local run_at
    run_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local reg_array
    reg_array=$(json_array_from_list ${REGRESSIONS[@]+"${REGRESSIONS[@]}"})

    local overall_passed=true
    if [[ $PHASES_FAILED -gt 0 ]]; then
        overall_passed=false
    fi

    local phases_json
    phases_json=$(jq -n \
        --argjson cold "$COLD_CACHE_RESULT" \
        --argjson warm "$WARM_CACHE_RESULT" \
        --argjson saturation "$SATURATION_RESULT" \
        --argjson ttw "$TTW_RESULT" \
        '{
            cold_cache: $cold,
            warm_cache: $warm,
            saturation: $saturation,
            time_to_warm: $ttw
        }')

    jq -n \
        --arg benchmark_id "$benchmark_id" \
        --arg run_at "$run_at" \
        --arg script_version "$SCRIPT_VERSION" \
        --arg target "$TARGET" \
        --argjson port "$PORT" \
        --arg mode "$MODE" \
        --arg clear_mode "$CLEAR_MODE" \
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
        --argjson stats_sources "$STATS_SOURCES_JSON" \
        --argjson baseline "$BASELINE_JSON" \
        --arg precache_state "$PRECACHE_STATE" \
        --arg dnsperf_version "${DNSPERF_VERSION:-}" \
        '{
            benchmark_id: $benchmark_id,
            run_at: $run_at,
            script_version: $script_version,
            config: {
                target: $target,
                port: $port,
                mode: $mode,
                clear_mode: $clear_mode,
                corpus: $corpus,
                duration_seconds: $duration
            },
            environment: {
                hostname: $hostname,
                os: $os,
                kernel: $kernel,
                dnsperf_version: (if $dnsperf_version == "" then null else $dnsperf_version end)
            },
            prerequisites: $prereq,
            stats_sources: $stats_sources,
            precache_pause: $precache_state,
            phases: $phases,
            baseline: $baseline,
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
    local benchmark_id
    benchmark_id="bm-$(date +%Y%m%d-%H%M%S)"
    local run_at
    run_at=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

    local cold_status="SKIP" cold_qps="-" cold_p50="-" cold_p95="-" cold_p99="-" cold_notes=""
    local warm_status="SKIP" warm_qps="-" warm_p50="-" warm_p95="-" warm_p99="-" warm_notes=""
    local sat_status="SKIP" sat_qps="-" sat_notes=""
    local ttw_status="SKIP" ttw_time="-" ttw_notes=""

    if [[ "$COLD_CACHE_RESULT" != "null" ]]; then
        if jq -e '.passed == true' <<< "$COLD_CACHE_RESULT" &>/dev/null; then cold_status="PASS"; else cold_status="FAIL"; fi
        cold_qps=$(jq -r '.metrics.qps_actual // "-"' <<< "$COLD_CACHE_RESULT")
        cold_p50=$(jq -r '.metrics.p50_latency_ms // "-"' <<< "$COLD_CACHE_RESULT")
        cold_p95=$(jq -r '.metrics.p95_latency_ms // "-"' <<< "$COLD_CACHE_RESULT")
        cold_p99=$(jq -r '.metrics.p99_latency_ms // "-"' <<< "$COLD_CACHE_RESULT")
        cold_notes="clear: $(jq -r '.clear.mode // "-"' <<< "$COLD_CACHE_RESULT")"
    fi

    if [[ "$WARM_CACHE_RESULT" != "null" ]]; then
        if jq -e '.passed == true' <<< "$WARM_CACHE_RESULT" &>/dev/null; then warm_status="PASS"; else warm_status="FAIL"; fi
        warm_qps=$(jq -r '.metrics.qps_actual // "-"' <<< "$WARM_CACHE_RESULT")
        warm_p50=$(jq -r '.metrics.p50_latency_ms // "-"' <<< "$WARM_CACHE_RESULT")
        warm_p95=$(jq -r '.metrics.p95_latency_ms // "-"' <<< "$WARM_CACHE_RESULT")
        warm_p99=$(jq -r '.metrics.p99_latency_ms // "-"' <<< "$WARM_CACHE_RESULT")
        warm_notes="dnsdist hit: $(jq -r '.counter_deltas.dnsdist.hit_ratio_pct // "-"' <<< "$WARM_CACHE_RESULT")%"
    fi

    if [[ "$SATURATION_RESULT" != "null" ]]; then
        if jq -e '.passed == true' <<< "$SATURATION_RESULT" &>/dev/null; then sat_status="PASS"; else sat_status="FAIL"; fi
        sat_qps=$(jq -r '.metrics.max_qps_sustained // "-"' <<< "$SATURATION_RESULT")
        sat_notes="$(jq -r '.method // "-"' <<< "$SATURATION_RESULT")"
    fi

    if [[ "$TTW_RESULT" != "null" ]]; then
        if jq -e '.passed == true' <<< "$TTW_RESULT" &>/dev/null; then ttw_status="PASS"; else ttw_status="FAIL"; fi
        ttw_time=$(jq -r '.metrics.time_to_warm_s // "-"' <<< "$TTW_RESULT")
        [[ "$ttw_time" != "-" ]] && ttw_time="${ttw_time}s"
        ttw_notes="$(jq -r '.metrics.required_consecutive_windows // "-"' <<< "$TTW_RESULT") windows x $(jq -r '.metrics.window_seconds // "-"' <<< "$TTW_RESULT")s"
    fi

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
**Clear mode**: $CLEAR_MODE  
**Stats sources**: dnsdist=$(jq -r '.dnsdist // "none"' <<< "$STATS_SOURCES_JSON"), recursor=$(jq -r '.recursor // "none"' <<< "$STATS_SOURCES_JSON")  
**Precache pause**: $PRECACHE_STATE  

## Summary

| Phase | Status | QPS | p50 | p95 | p99 | Notes |
|-------|--------|-----|-----|-----|-----|-------|
| Cold Cache | $cold_status | $cold_qps | ${cold_p50}ms | ${cold_p95}ms | ${cold_p99}ms | $cold_notes |
| Warm Cache | $warm_status | $warm_qps | ${warm_p50}ms | ${warm_p95}ms | ${warm_p99}ms | $warm_notes |
| Saturation | $sat_status | $sat_qps | - | - | - | $sat_notes |
| Time-to-Warm | $ttw_status | - | - | - | - | $ttw_time, $ttw_notes |

## Verdict

$verdict

---
*Generated by dns53-benchmark.sh v${SCRIPT_VERSION}*
EOF
}

# =============================================================================
# SELF-TEST (offline: no docker, no dnsperf, no network)
# =============================================================================

SELF_TEST_FAILURES=0

st_check() {
    local name="$1" rc="$2"
    if [[ "$rc" -eq 0 ]]; then
        log_pass "self-test: $name"
    else
        log_fail "self-test: $name"
        SELF_TEST_FAILURES=$((SELF_TEST_FAILURES + 1))
    fi
}

self_test() {
    log_section "Self-Test (offline: no docker, no dnsperf, no network)"
    local tmp
    mkdir -p /tmp/opencode 2>/dev/null || true
    tmp=$(mktemp -d /tmp/opencode/dns53-selftest.XXXXXX 2>/dev/null || mktemp -d)

    # ---- T1: flag parsing -------------------------------------------------
    (
        MODE=all CLEAR_MODE=console OUTPUT=json DURATION=60 TTW_WINDOWS=5 TTW_WINDOW_SECONDS=30 TTW_QPS=500
        validate_args
    ) >/dev/null 2>&1
    st_check "T1a valid args accepted" $?

    (
        MODE=all CLEAR_MODE=nuke-everything OUTPUT=json DURATION=60 TTW_WINDOWS=5 TTW_WINDOW_SECONDS=30 TTW_QPS=500
        validate_args
    ) >/dev/null 2>&1
    rc=$?
    if [[ $rc -eq $EXIT_CONFIG_ERROR ]]; then
        st_check "T1b unrecognized --clear-mode refused with exit $EXIT_CONFIG_ERROR" 0
    else
        st_check "T1b unrecognized --clear-mode refused with exit $EXIT_CONFIG_ERROR (got $rc)" 1
    fi

    (
        MODE=bogus CLEAR_MODE=console OUTPUT=json DURATION=60 TTW_WINDOWS=5 TTW_WINDOW_SECONDS=30 TTW_QPS=500
        validate_args
    ) >/dev/null 2>&1
    rc=$?
    if [[ $rc -eq $EXIT_CONFIG_ERROR ]]; then
        st_check "T1c invalid mode refused" 0
    else
        st_check "T1c invalid mode refused (got $rc)" 1
    fi

    (
        MODE=time-to-warm CLEAR_MODE=console OUTPUT=json DURATION=60 TTW_WINDOWS=0 TTW_WINDOW_SECONDS=30 TTW_QPS=500
        validate_args
    ) >/dev/null 2>&1
    rc=$?
    if [[ $rc -eq $EXIT_CONFIG_ERROR ]]; then
        st_check "T1d zero warm-windows refused" 0
    else
        st_check "T1d zero warm-windows refused (got $rc)" 1
    fi

    # ---- T2: clearing plan output ------------------------------------------
    local plan
    plan=$(print_clearing_plan console)
    if printf '%s' "$plan" | grep -q "wipe-cache" && printf '%s' "$plan" | grep -q "expunge(0)" && \
       printf '%s' "$plan" | grep -q "DNSDIST_CONSOLE_KEY"; then
        st_check "T2a console clearing plan lists both layers + prerequisite" 0
    else
        st_check "T2a console clearing plan lists both layers + prerequisite" 1
    fi

    plan=$(print_clearing_plan restart)
    if printf '%s' "$plan" | grep -q "docker restart" && printf '%s' "$plan" | grep -q "DESTRUCTIVE" && \
       printf '%s' "$plan" | grep -q "healthy"; then
        st_check "T2b restart clearing plan is explicit about destruction + health wait" 0
    else
        st_check "T2b restart clearing plan is explicit about destruction + health wait" 1
    fi

    if print_clearing_plan "nuke" &>/dev/null; then
        st_check "T2c unrecognized clearing target refused" 1
    else
        st_check "T2c unrecognized clearing target refused" 0
    fi

    # ---- T3: failing clear aborts before dnsperf ----------------------------
    # Stub the clear primitives to fail, then verify do_clear fails AND that a
    # guarded phase never invokes dnsperf (sentinel file must not appear).
    # console_available is stubbed so the tests exercise the intended failure
    # point regardless of whether the host happens to run the compose stack.
    console_available() { return 0; }
    clear_recursor_console() { return 1; }
    CLEAR_MODE=console
    CLEAR_REPORT="null"
    if do_clear >/dev/null 2>&1; then
        st_check "T3a failed recursor clear aborts do_clear" 1
    else
        st_check "T3a failed recursor clear aborts do_clear" 0
    fi

    clear_recursor_console() { log_info "stubbed recursor clear ok"; return 0; }
    clear_dnsdist_console() { return 1; }
    if do_clear >/dev/null 2>&1; then
        st_check "T3b failed dnsdist clear aborts do_clear" 1
    else
        st_check "T3b failed dnsdist clear aborts do_clear" 0
    fi

    # Floor verification failure also aborts:
    clear_dnsdist_console() { log_info "stubbed dnsdist clear ok"; return 0; }
    collect_stats() {
        STATS_JSON='{"dnsdist": {"hits": 10, "misses": 0, "entries": 42, "maxEntries": 100},
                     "recursor": {"cache_entries": 7, "packetcache_entries": 0}}'
        STATS_DD_SOURCE="stub"; STATS_REC_SOURCE="stub"
    }
    if do_clear >/dev/null 2>&1; then
        st_check "T3c non-empty cache floor aborts do_clear" 1
    else
        st_check "T3c non-empty cache floor aborts do_clear" 0
    fi

    local sentinel="${tmp}/dnsperf-ran"
    run_dnsperf() { touch "$sentinel"; return 0; }
    collect_stats() {
        STATS_JSON='{"dnsdist": {"hits": 10, "misses": 0, "entries": 0, "maxEntries": 100},
                     "recursor": {"cache_entries": 0, "packetcache_entries": 0}}'
        STATS_DD_SOURCE="stub"; STATS_REC_SOURCE="stub"
    }
    clear_dnsdist_console() { return 1; }  # clearing fails again
    RESULTS_DIR="$tmp"
    DURATION=1
    CORPUS="/dev/null"
    TARGET="127.0.0.1"; PORT="53"
    COLD_CACHE_RESULT="null"; PHASES_RUN=0; PHASES_FAILED=0; REGRESSIONS=(); CLEAR_FAILED=false
    run_cold_cache_phase >/dev/null 2>&1
    rc=$?
    if [[ $rc -ne 0 && ! -f "$sentinel" && "$CLEAR_FAILED" == "true" ]]; then
        st_check "T3d cold phase aborts before dnsperf when clearing fails (flags prereq failure)" 0
    else
        st_check "T3d cold phase aborts before dnsperf when clearing fails (flags prereq failure)" 1
    fi
    unset -f run_dnsperf collect_stats clear_dnsdist_console clear_recursor_console console_available

    # ---- T4: counter delta computation on synthetic fixtures ---------------
    local pre post deltas
    pre='{"dnsdist": {"hits": 100, "misses": 10, "entries": 5, "maxEntries": 100},
          "recursor": {"packetcache_hits": 50, "packetcache_misses": 50, "cache_hits": 20, "cache_misses": 80,
                       "cache_entries": 5, "packetcache_entries": 5, "max_cache_entries": 1000, "max_packetcache_entries": 1000}}'
    post='{"dnsdist": {"hits": 250, "misses": 35, "entries": 9, "maxEntries": 100},
          "recursor": {"packetcache_hits": 350, "packetcache_misses": 100, "cache_hits": 170, "cache_misses": 130,
                       "cache_entries": 9, "packetcache_entries": 9, "max_cache_entries": 1000, "max_packetcache_entries": 1000}}'
    deltas=$(compute_layer_deltas "$pre" "$post")
    local ok=true
    [[ $(jq -r '.dnsdist.hits' <<< "$deltas") == 150 ]] || ok=false
    [[ $(jq -r '.dnsdist.misses' <<< "$deltas") == 25 ]] || ok=false
    [[ $(jq -r '.dnsdist.hit_ratio_pct' <<< "$deltas") == 85.7 ]] || ok=false
    [[ $(jq -r '.recursor_packetcache.hits' <<< "$deltas") == 300 ]] || ok=false
    # packetcache: 300 hits / 50 misses -> 85.7%
    [[ $(jq -r '.recursor_packetcache.hit_ratio_pct' <<< "$deltas") == 85.7 ]] || ok=false
    # recordcache: 150 hits / 50 misses -> 75%
    [[ $(jq -r '.recursor_recordcache.hit_ratio_pct' <<< "$deltas") == 75 ]] || ok=false
    $ok && st_check "T4a delta + ratio computation on fixtures" 0 || st_check "T4a delta + ratio computation on fixtures" 1

    # null layers stay null (clean degradation, not fake zeros)
    deltas=$(compute_layer_deltas '{"dnsdist": null, "recursor": null}' "$post")
    if [[ $(jq -r '.dnsdist.hit_ratio_pct' <<< "$deltas") == "null" ]] && \
       [[ $(jq -r '.recursor_packetcache.hit_ratio_pct' <<< "$deltas") == "null" ]]; then
        st_check "T4b null stats yield null ratios" 0
    else
        st_check "T4b null stats yield null ratios" 1
    fi

    # ---- T5: p99 gating logic ------------------------------------------------
    if latency_gate 45 50 "unit-p99" >/dev/null 2>&1; then
        st_check "T5a latency under limit passes" 0
    else
        st_check "T5a latency under limit passes" 1
    fi
    if latency_gate 55 50 "unit-p99" >/dev/null 2>&1; then
        st_check "T5b latency over limit fails" 1
    else
        st_check "T5b latency over limit fails" 0
    fi
    if latency_gate null 50 "unit-p99" >/dev/null 2>&1; then
        st_check "T5c null latency fails closed" 1
    else
        st_check "T5c null latency fails closed" 0
    fi
    if ratio_gate 89.9 90 "unit-ratio" >/dev/null 2>&1; then
        st_check "T5d ratio below target fails" 1
    else
        st_check "T5d ratio below target fails" 0
    fi
    if ratio_gate null 90 "unit-ratio" >/dev/null 2>&1; then
        st_check "T5e null ratio fails closed" 1
    else
        st_check "T5e null ratio fails closed" 0
    fi

    # ---- T6: dnsperf output parsing on real-format fixtures ------------------
    # Fixture 1: real dnsperf 2.16.0 text output shape (histogram), 8 samples.
    local fx="${tmp}/dnsperf-ok.txt"
    cat > "$fx" << 'FIXTURE'
DNS Performance Testing Tool
Version 2.16.0

[Status] Command line: dnsperf -s 127.0.0.1 -p 53 -d /tmp/q.txt -l 4 -Q 50 -m udp -O latency-histogram
[Status] Sending queries (to 127.0.0.1:53)
[Status] Started at: Wed Aug 19 04:30:42 2026
[Status] Stopping after 4.000000 seconds
[Status] Testing complete (time limit)

Statistics:

  Queries sent:         8
  Queries completed:    8 (100.00%)
  Queries lost:         0 (0.00%)

  Response codes:       NOERROR 8 (100.00%)
  Average packet size:  request 30, response 57
  Run time (s):         4.000019
  Queries per second:   1.999976

  Average Latency (s):  0.000304 (min 0.000083, max 0.023755)
  Latency StdDev (s):   0.001685
  Latency bucket (s):   answer count
  0.000082 - 0.000083:  1
  0.000100 - 0.000101:  2
  0.000102 - 0.000103:  2
  0.000104 - 0.000105:  2
  0.023754 - 0.023755:  1
FIXTURE
    if parse_dnsperf_output "$fx" >/dev/null 2>&1; then
        st_check "T6a known dnsperf format parses" 0
    else
        st_check "T6a known dnsperf format parses" 1
    fi
    ok=true
    [[ $(jq -r '.queries_sent' <<< "$DNSPERF_PARSED") == 8 ]] || ok=false
    [[ $(jq -r '.histogram_samples' <<< "$DNSPERF_PARSED") == 8 ]] || ok=false
    # sorted cumulative: p50 -> rank 4 lands in bucket ending 0.000103 -> 0.103ms
    [[ $(jq -r '.p50_latency_ms' <<< "$DNSPERF_PARSED") == 0.103 ]] || ok=false
    # p95 -> rank 7.6: cumulative reaches 7 after 4 buckets (< 7.6), so the
    # sample lies in the final bucket -> 23.755ms
    [[ $(jq -r '.p95_latency_ms' <<< "$DNSPERF_PARSED") == 23.755 ]] || ok=false
    # p99 -> rank 7.92 -> last bucket (0.023755) -> 23.755ms
    [[ $(jq -r '.p99_latency_ms' <<< "$DNSPERF_PARSED") == 23.755 ]] || ok=false
    [[ $(jq -r '.avg_latency_ms' <<< "$DNSPERF_PARSED") == 0.304 ]] || ok=false
    $ok && st_check "T6b histogram percentiles computed correctly" 0 || st_check "T6b histogram percentiles computed correctly" 1

    # Fixture 2: unknown format -> loud failure, no null percentiles
    printf 'some other tool output\nQueries: 5\n' > "$fx"
    if parse_dnsperf_output "$fx" >/dev/null 2>&1; then
        st_check "T6c unknown output format fails loudly" 1
    else
        st_check "T6c unknown output format fails loudly" 0
    fi

    # Fixture 3: right banner but no histogram -> loud failure
    printf 'DNS Performance Testing Tool\nVersion 2.16.0\nQueries sent:         5\nQueries completed:    5 (100.00%%)\nQueries lost:         0 (0.00%%)\nRun time (s):         5.0\nQueries per second:   1.0\nAverage Latency (s):  0.001 (min 0.001, max 0.001)\n' > "$fx"
    if parse_dnsperf_output "$fx" >/dev/null 2>&1; then
        st_check "T6d missing histogram fails loudly" 1
    else
        st_check "T6d missing histogram fails loudly" 0
    fi

    # ---- T7: rec_control values-only parsing ---------------------------------
    local vals
    if vals=$(parse_rec_control_values $'123\n45\n7\n1000\n8\n9\n10\n2000' 8); then
        local -a vv
        read -r -a vv <<< "$vals"
        if [[ "${vv[0]}" == 123 && "${vv[7]}" == 2000 ]]; then
            st_check "T7a rec_control value block parses" 0
        else
            st_check "T7a rec_control value block parses" 1
        fi
    else
        st_check "T7a rec_control value block parses" 1
    fi

    if parse_rec_control_values $'123\nUNKNOWN\n7\n1000\n8\n9\n10\n2000' 8 >/dev/null 2>&1; then
        st_check "T7b rec_control UNKNOWN stat fails closed" 1
    else
        st_check "T7b rec_control UNKNOWN stat fails closed" 0
    fi

    if parse_rec_control_values $'123\n45' 8 >/dev/null 2>&1; then
        st_check "T7c truncated rec_control output fails closed" 1
    else
        st_check "T7c truncated rec_control output fails closed" 0
    fi

    # ---- T8: version comparison ----------------------------------------------
    local ok=true
    version_ge 2.16.0 2.14.0 || ok=false
    version_ge 2.14.0 2.14.0 || ok=false
    version_ge 2.14.1 2.14.0 || ok=false
    if version_ge 2.9.2 2.14.0; then ok=false; fi
    if version_ge 2.13.9 2.14.0; then ok=false; fi
    $ok && st_check "T8 dnsperf version gate comparisons" 0 || st_check "T8 dnsperf version gate comparisons" 1

    # ---- T9: jsonstat pool extraction (synthetic) -----------------------------
    local pools dd
    pools='{"pools": [{"id": 0, "name": "", "cacheSize": 500000, "cacheEntries": 1234, "cacheHits": 100, "cacheMisses": 5}]}'
    dd=$(printf '%s' "$pools" | jq -c '([.pools[] | select(.name == "")] | first) // {} |
            if has("cacheHits") then
                {hits: (.cacheHits // 0), misses: (.cacheMisses // 0),
                 entries: (.cacheEntries // 0), maxEntries: (.cacheSize // 0)}
            else null end')
    if [[ $(jq -r '.entries' <<< "$dd") == 1234 && $(jq -r '.maxEntries' <<< "$dd") == 500000 ]]; then
        st_check "T9 jsonstat default-pool extraction" 0
    else
        st_check "T9 jsonstat default-pool extraction" 1
    fi

    # ---- T10: cache floor tolerance -------------------------------------------
    # dnsdist must be strictly empty; the recursor tolerates a couple of
    # background housekeeping entries (security-status poll) but not more.
    if verify_cache_floor '{"dnsdist": {"entries": 0}, "recursor": {"cache_entries": 1, "packetcache_entries": 2}}' >/dev/null 2>&1; then
        st_check "T10a recursor housekeeping entries within tolerance pass" 0
    else
        st_check "T10a recursor housekeeping entries within tolerance pass" 1
    fi
    if verify_cache_floor '{"dnsdist": {"entries": 0}, "recursor": {"cache_entries": 500, "packetcache_entries": 0}}' >/dev/null 2>&1; then
        st_check "T10b recursor occupancy above tolerance fails closed" 1
    else
        st_check "T10b recursor occupancy above tolerance fails closed" 0
    fi
    # Live-observed quiescent steady state on a fully primed recursor:
    # 13 root NS + A/AAAA glue + security poll (~57 entries, zero traffic).
    if verify_cache_floor '{"dnsdist": {"entries": 0}, "recursor": {"cache_entries": 57, "packetcache_entries": 1}}' >/dev/null 2>&1; then
        st_check "T10b2 primed-recursor housekeeping occupancy (57) passes" 0
    else
        st_check "T10b2 primed-recursor housekeeping occupancy (57) passes" 1
    fi
    if verify_cache_floor '{"dnsdist": {"entries": 1}, "recursor": {"cache_entries": 0, "packetcache_entries": 0}}' >/dev/null 2>&1; then
        st_check "T10c any dnsdist entry fails closed (strict zero)" 1
    else
        st_check "T10c any dnsdist entry fails closed (strict zero)" 0
    fi

    # ---- T11: report JSON generation ------------------------------------------
    # Version strings like 2.16.0 are NOT valid JSON numbers; the generator
    # must pass them as strings (regression test for a real bug found here).
    local saved_corpus="$CORPUS"
    CORPUS="/dev/null"
    DNSPERF_VERSION="2.16.0"
    PREREQ_JSON='{"dnsperf": {"installed": true, "version": "2.16.0"}}'
    STATS_SOURCES_JSON='{"dnsdist": "dnsdist-console", "recursor": "rec_control"}'
    PRECACHE_STATE="paused"
    PHASES_RUN=1; PHASES_PASSED=1; PHASES_FAILED=0
    TTW_RESULT='{"implemented": true, "passed": true, "metrics": {"time_to_warm_s": 187, "windows_run": 9, "required_consecutive_windows": 5, "window_seconds": 30, "load_qps": 500}}'
    BASELINE_JSON='{"cache_occupancy": {}, "containers": [], "host_memory": {}, "recursor_threads_cpu_msec": {}, "dnstap_processor": "healthy"}'
    if generate_json_output 2>/dev/null | jq -e \
        '.summary.passed == true and .phases.time_to_warm.metrics.time_to_warm_s == 187 and .environment.dnsperf_version == "2.16.0" and .stats_sources.recursor == "rec_control"' >/dev/null 2>&1; then
        st_check "T11a report JSON generates valid, complete output" 0
    else
        st_check "T11a report JSON generates valid, complete output" 1
    fi
    DNSPERF_VERSION=""
    if generate_json_output 2>/dev/null | jq -e '.environment.dnsperf_version == null' >/dev/null 2>&1; then
        st_check "T11b missing dnsperf version degrades to null" 0
    else
        st_check "T11b missing dnsperf version degrades to null" 1
    fi
    if generate_markdown_output 2>/dev/null | grep -q "Time-to-Warm"; then
        st_check "T11c markdown report includes time-to-warm row" 0
    else
        st_check "T11c markdown report includes time-to-warm row" 1
    fi
    CORPUS="$saved_corpus"
    TTW_RESULT="null"; BASELINE_JSON="null"; PREREQ_JSON='{}'
    STATS_SOURCES_JSON='{"dnsdist": null, "recursor": null}'
    PRECACHE_STATE="not-paused"; PHASES_RUN=0; PHASES_PASSED=0; PHASES_FAILED=0

    rm -rf "$tmp"

    log_section "Self-Test Result"
    if [[ $SELF_TEST_FAILURES -eq 0 ]]; then
        log_pass "ALL SELF-TESTS PASSED"
        return 0
    fi
    log_fail "${SELF_TEST_FAILURES} SELF-TEST(S) FAILED"
    return 1
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
            --clear-mode)
                CLEAR_MODE="$2"
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
            --warm-windows)
                TTW_WINDOWS="$2"
                shift 2
                ;;
            --warm-window-seconds)
                TTW_WINDOW_SECONDS="$2"
                shift 2
                ;;
            --ttw-qps)
                TTW_QPS="$2"
                shift 2
                ;;
            --no-precache-pause)
                PRECACHE_PAUSE="false"
                shift
                ;;
            --strict-quiesce)
                STRICT_QUIESCE="true"
                shift
                ;;
            --output)
                OUTPUT="$2"
                shift 2
                ;;
            --results-dir)
                RESULTS_DIR="$2"
                shift 2
                ;;
            --self-test)
                self_test
                exit $?
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

    # Step 1: Validate arguments
    if ! validate_args; then
        log_fail "Configuration invalid"
        exit $EXIT_CONFIG_ERROR
    fi

    # Step 2: Check prerequisites
    if ! check_prerequisites; then
        log_fail "Prerequisites not met"
        exit $EXIT_PREREQ_FAILED
    fi

    # Step 3: Validate configuration
    if ! validate_config; then
        log_fail "Configuration invalid"
        exit $EXIT_CONFIG_ERROR
    fi

    # Step 4: Preflight container health for measurement phases (both layers
    # must be healthy before any counters are taken or traffic is sent). This
    # runs BEFORE stats-source detection so a still-starting container is
    # waited for rather than misreported as a missing counter source.
    local needs_counters=false
    case "$MODE" in
        cold|warm|time-to-warm) needs_counters=true ;;
        all) needs_counters=true ;;
    esac
    if [[ "$needs_counters" == "true" ]]; then
        log_section "Container Health Preflight"
        local c
        for c in "$DNSDIST_CONTAINER" "$RECURSOR_CONTAINER"; do
            if ! container_running "$c"; then
                log_fail "Container $c is not running - aborting (counters/clearing would be meaningless)"
                exit $EXIT_PREREQ_FAILED
            fi
            if ! wait_container_healthy "$c" 120; then
                log_fail "Container $c failed the health preflight - aborting"
                exit $EXIT_PREREQ_FAILED
            fi
            log_pass "$c healthy"
        done
    fi

    # Step 5: Detect counter sources (per layer, clean degradation). Counter-
    # dependent modes fail closed BEFORE any traffic or destructive action.
    log_section "Statistics Source Detection"
    collect_stats
    if [[ "$needs_counters" == "true" ]]; then
        if ! require_stats_sources; then
            exit $EXIT_PREREQ_FAILED
        fi
    else
        log_info "Mode '$MODE' does not gate on cache counters; sources: dnsdist=${STATS_DD_SOURCE:-none} recursor=${STATS_REC_SOURCE:-none}"
    fi

    # Step 6: Pause the admin-ui precache warming job for the measurement
    # (restored on exit via the trap installed below).
    if ! precache_pause; then
        precache_resume || true
        exit $EXIT_PREREQ_FAILED
    fi

    # Step 7: Capture the baseline snapshot (occupancy, memory, threads,
    # dnstap-processor health) before any traffic.
    collect_stats
    capture_baseline

    # Step 8: Run benchmark phases
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
        time-to-warm)
            run_ttw_phase || true
            ;;
        all)
            run_cold_cache_phase || true
            if [[ "$ABORT_REMAINING_PHASES" != "true" ]]; then
                run_warm_cache_phase || true
            else
                log_fail "Skipping warm phase: aborted after cold-phase failure"
            fi
            if [[ "$ABORT_REMAINING_PHASES" != "true" ]]; then
                run_saturation_phase || true
            else
                log_fail "Skipping saturation phase: aborted after earlier failure"
            fi
            ;;
    esac

    # Step 9: Restore precache warming (the EXIT trap is a safety net)
    precache_resume || true

    # Step 10: Generate output
    log_section "Generating Output"

    local timestamp
    timestamp=$(date +%Y%m%d-%H%M%S)
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

    log_info "Phases run: $PHASES_RUN | Passed: $PHASES_PASSED | Failed: $PHASES_FAILED"

    # A failed/unverifiable cache clear is a prerequisite failure (exit 2),
    # not a performance regression (exit 1) - see the exit-code contract.
    if [[ "$CLEAR_FAILED" == "true" ]]; then
        log_fail "Cache clearing failed or could not be verified - no benchmark was measured"
        exit $EXIT_PREREQ_FAILED
    fi

    if [[ $PHASES_FAILED -gt 0 ]]; then
        log_fail "Performance regression detected!"
        exit $EXIT_PHASE_FAILED
    fi

    exit $EXIT_SUCCESS
}

# Safety net: always try to restore precache warming on any exit path.
trap 'precache_resume >/dev/null 2>&1 || true' EXIT

# Run main with all arguments
main "$@"
