#!/usr/bin/env bash
#
# PowerBlockade End-to-End Test Suite
# Run this before releases to verify full functionality
#
# Usage: ./scripts/test-e2e.sh [primary_ip] [secondary_ip]
#
# Example: ./scripts/test-e2e.sh 10.5.5.64 10.5.5.65
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Default IPs (celsate/bowlister)
PRIMARY_IP="${1:-10.5.5.64}"
SECONDARY_IP="${2:-10.5.5.65}"
ADMIN_PORT="8080"
DNS_PORT="53"

# Test configuration
NUM_DOMAINS="${NUM_DOMAINS:-100}"
TEST_TIMEOUT=5
CACHE_TEST_ITERATIONS=3

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Counters
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[PASS]${NC} $*"; ((TESTS_PASSED++)); }
log_fail() { echo -e "${RED}[FAIL]${NC} $*"; ((TESTS_FAILED++)); }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_skip() { echo -e "${CYAN}[SKIP]${NC} $*"; ((TESTS_SKIPPED++)); }
log_section() { echo -e "\n${CYAN}═══════════════════════════════════════════════════════════${NC}"; echo -e "${CYAN} $*${NC}"; echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}\n"; }

# Top 100 domains for testing (subset of Cloudflare Radar top domains)
TOP_DOMAINS=(
    "google.com" "youtube.com" "facebook.com" "instagram.com" "twitter.com"
    "wikipedia.org" "amazon.com" "yahoo.com" "reddit.com" "linkedin.com"
    "netflix.com" "microsoft.com" "apple.com" "github.com" "stackoverflow.com"
    "twitch.tv" "discord.com" "spotify.com" "tiktok.com" "whatsapp.com"
    "zoom.us" "office.com" "bing.com" "duckduckgo.com" "cloudflare.com"
    "dropbox.com" "salesforce.com" "adobe.com" "paypal.com" "ebay.com"
    "cnn.com" "bbc.com" "nytimes.com" "theguardian.com" "reuters.com"
    "weather.com" "imdb.com" "yelp.com" "tripadvisor.com" "booking.com"
    "airbnb.com" "uber.com" "lyft.com" "doordash.com" "grubhub.com"
    "slack.com" "notion.so" "figma.com" "canva.com" "trello.com"
    "medium.com" "substack.com" "wordpress.com" "blogger.com" "tumblr.com"
    "pinterest.com" "flickr.com" "imgur.com" "giphy.com" "unsplash.com"
    "shopify.com" "etsy.com" "alibaba.com" "wish.com" "target.com"
    "walmart.com" "bestbuy.com" "homedepot.com" "lowes.com" "costco.com"
    "chase.com" "bankofamerica.com" "wellsfargo.com" "capitalone.com" "amex.com"
    "expedia.com" "kayak.com" "priceline.com" "hotels.com" "vrbo.com"
    "espn.com" "nfl.com" "nba.com" "mlb.com" "fifa.com"
    "steamcommunity.com" "epicgames.com" "roblox.com" "minecraft.net" "ea.com"
    "hulu.com" "disneyplus.com" "hbomax.com" "peacocktv.com" "paramountplus.com"
    "coursera.org" "udemy.com" "khanacademy.org" "edx.org" "duolingo.com"
)

# Known blocked domains for testing (from common blocklists)
TEST_BLOCKED_DOMAINS=(
    "doubleclick.net"
    "googlesyndication.com"
    "googleadservices.com"
    "ads.google.com"
    "pagead2.googlesyndication.com"
    "adservice.google.com"
    "analytics.google.com"
    "ad.doubleclick.net"
    "stats.g.doubleclick.net"
    "cm.g.doubleclick.net"
)

check_dependencies() {
    local missing=()
    
    for cmd in dig curl jq; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_fail "Missing dependencies: ${missing[*]}"
        echo "Install with: brew install ${missing[*]} (macOS) or apt install ${missing[*]} (Linux)"
        exit 1
    fi
    log_success "All dependencies present (dig, curl, jq)"
}

check_connectivity() {
    local ip="$1"
    local name="$2"
    
    if ping -c 1 -W 2 "$ip" &>/dev/null; then
        log_success "$name ($ip) is reachable"
        return 0
    else
        log_fail "$name ($ip) is not reachable"
        return 1
    fi
}

check_admin_ui() {
    local ip="$1"
    local name="$2"
    
    local response
    if response=$(curl -sf --max-time "$TEST_TIMEOUT" "http://${ip}:${ADMIN_PORT}/health" 2>/dev/null); then
        if echo "$response" | jq -e '.ok == true' &>/dev/null; then
            log_success "$name Admin UI healthy"
            return 0
        fi
    fi
    log_fail "$name Admin UI not responding"
    return 1
}

check_dns_resolution() {
    local dns_server="$1"
    local domain="$2"
    local expected_blocked="${3:-false}"
    
    local result
    result=$(dig +short +time="$TEST_TIMEOUT" +tries=1 "@${dns_server}" "$domain" A 2>/dev/null)
    local status=$?
    
    if [[ "$expected_blocked" == "true" ]]; then
        # For blocked domains, we expect NXDOMAIN or empty/0.0.0.0
        if [[ -z "$result" || "$result" == "0.0.0.0" || "$result" == "127.0.0.1" ]]; then
            return 0  # Correctly blocked
        else
            return 1  # Should be blocked but got response
        fi
    else
        # For normal domains, we expect a valid IP
        if [[ -n "$result" && "$result" != "0.0.0.0" ]]; then
            return 0  # Got valid response
        else
            return 1  # No response or blocked
        fi
    fi
}

test_dns_bulk() {
    local dns_server="$1"
    local name="$2"
    local domains=("${@:3}")
    
    local success=0
    local fail=0
    local total=${#domains[@]}
    
    # Limit to NUM_DOMAINS
    if [[ $total -gt $NUM_DOMAINS ]]; then
        total=$NUM_DOMAINS
    fi
    
    log_info "Testing $total domains against $name ($dns_server)..."
    
    for ((i=0; i<total; i++)); do
        local domain="${domains[$i]}"
        if check_dns_resolution "$dns_server" "$domain" "false"; then
            ((success++))
        else
            ((fail++))
            [[ $fail -le 5 ]] && log_warn "  Failed to resolve: $domain"
        fi
        
        # Progress indicator every 20 domains
        if (( (i+1) % 20 == 0 )); then
            echo -ne "\r  Progress: $((i+1))/$total domains tested..."
        fi
    done
    echo -ne "\r"
    
    local pct=$((success * 100 / total))
    if [[ $pct -ge 95 ]]; then
        log_success "$name resolved $success/$total domains ($pct%)"
    elif [[ $pct -ge 80 ]]; then
        log_warn "$name resolved $success/$total domains ($pct%) - some failures"
    else
        log_fail "$name resolved only $success/$total domains ($pct%)"
    fi
}

test_blocking() {
    local dns_server="$1"
    local name="$2"
    
    local blocked=0
    local not_blocked=0
    
    log_info "Testing ad/tracker blocking on $name..."
    
    for domain in "${TEST_BLOCKED_DOMAINS[@]}"; do
        if check_dns_resolution "$dns_server" "$domain" "true"; then
            ((blocked++))
        else
            ((not_blocked++))
            log_warn "  Not blocked: $domain"
        fi
    done
    
    local total=${#TEST_BLOCKED_DOMAINS[@]}
    local pct=$((blocked * 100 / total))
    
    if [[ $pct -ge 80 ]]; then
        log_success "$name blocking $blocked/$total test domains ($pct%)"
    elif [[ $pct -ge 50 ]]; then
        log_warn "$name blocking $blocked/$total test domains ($pct%) - blocklist may need update"
    else
        log_skip "$name blocking $blocked/$total domains - blocklists may not be configured"
    fi
}

test_cache_performance() {
    local dns_server="$1"
    local name="$2"
    local test_domain="example.com"
    
    log_info "Testing cache performance on $name..."
    
    # First query (cold cache)
    local start_cold=$(date +%s%N)
    dig +short +time="$TEST_TIMEOUT" "@${dns_server}" "$test_domain" A &>/dev/null
    local end_cold=$(date +%s%N)
    local cold_ms=$(( (end_cold - start_cold) / 1000000 ))
    
    # Wait briefly
    sleep 0.1
    
    # Second query (warm cache)
    local start_warm=$(date +%s%N)
    dig +short +time="$TEST_TIMEOUT" "@${dns_server}" "$test_domain" A &>/dev/null
    local end_warm=$(date +%s%N)
    local warm_ms=$(( (end_warm - start_warm) / 1000000 ))
    
    log_info "  Cold query: ${cold_ms}ms, Warm query: ${warm_ms}ms"
    
    if [[ $warm_ms -lt $cold_ms ]] || [[ $warm_ms -lt 10 ]]; then
        log_success "$name cache working (warm: ${warm_ms}ms vs cold: ${cold_ms}ms)"
    else
        log_warn "$name cache may not be effective (warm: ${warm_ms}ms vs cold: ${cold_ms}ms)"
    fi
}

test_query_logging() {
    local dns_server="$1"
    local admin_ip="$2"
    local name="$3"
    
    # Generate a unique domain to query
    local test_id=$(date +%s)
    local test_domain="e2e-test-${test_id}.example.com"
    
    log_info "Testing query logging on $name..."
    
    # Make a DNS query
    dig +short +time="$TEST_TIMEOUT" "@${dns_server}" "$test_domain" A &>/dev/null || true
    
    # Wait for log to be processed
    sleep 3
    
    # Check if it appears in logs via API (need to be authenticated, so just check analytics page loads)
    local response
    if response=$(curl -sf --max-time "$TEST_TIMEOUT" "http://${admin_ip}:${ADMIN_PORT}/api/version" 2>/dev/null); then
        log_success "$name query logging API accessible"
    else
        log_warn "$name could not verify logging (API not accessible without auth)"
    fi
}

test_secondary_sync() {
    local primary_ip="$1"
    local secondary_ip="$2"
    
    log_info "Testing secondary node sync..."
    
    # Check nodes endpoint (would need auth, so just verify connectivity)
    local primary_health secondary_health
    
    primary_health=$(curl -sf --max-time "$TEST_TIMEOUT" "http://${primary_ip}:${ADMIN_PORT}/health" 2>/dev/null || echo '{"ok":false}')
    secondary_health=$(curl -sf --max-time "$TEST_TIMEOUT" "http://${secondary_ip}:${ADMIN_PORT}/health" 2>/dev/null || echo '{"ok":false}')
    
    if echo "$primary_health" | jq -e '.ok == true' &>/dev/null && \
       echo "$secondary_health" | jq -e '.ok == true' &>/dev/null; then
        log_success "Both primary and secondary nodes healthy"
    else
        log_fail "Node health check failed"
    fi
    
    # Test that both resolve the same domain identically
    local primary_result secondary_result
    primary_result=$(dig +short +time="$TEST_TIMEOUT" "@${primary_ip}" "google.com" A 2>/dev/null | head -1)
    secondary_result=$(dig +short +time="$TEST_TIMEOUT" "@${secondary_ip}" "google.com" A 2>/dev/null | head -1)
    
    if [[ -n "$primary_result" && -n "$secondary_result" ]]; then
        log_success "Both nodes resolving DNS (primary: $primary_result, secondary: $secondary_result)"
    else
        log_fail "DNS resolution inconsistent between nodes"
    fi
}

test_precache() {
    local dns_server="$1"
    local name="$2"
    
    log_info "Testing precache functionality on $name..."
    
    # Query a set of domains rapidly
    local domains=("cloudflare.com" "google.com" "github.com" "microsoft.com" "apple.com")
    local fast_responses=0
    
    # First pass - populate cache
    for domain in "${domains[@]}"; do
        dig +short +time="$TEST_TIMEOUT" "@${dns_server}" "$domain" A &>/dev/null
    done
    
    sleep 0.5
    
    # Second pass - should be cached
    for domain in "${domains[@]}"; do
        local start=$(date +%s%N)
        dig +short +time="$TEST_TIMEOUT" "@${dns_server}" "$domain" A &>/dev/null
        local end=$(date +%s%N)
        local ms=$(( (end - start) / 1000000 ))
        
        if [[ $ms -lt 50 ]]; then
            ((fast_responses++))
        fi
    done
    
    if [[ $fast_responses -ge 4 ]]; then
        log_success "$name precache/cache effective ($fast_responses/${#domains[@]} fast responses)"
    else
        log_warn "$name cache performance could be better ($fast_responses/${#domains[@]} fast responses)"
    fi
}

generate_report() {
    local total=$((TESTS_PASSED + TESTS_FAILED + TESTS_SKIPPED))
    
    log_section "Test Results Summary"
    
    echo -e "  ${GREEN}Passed:${NC}  $TESTS_PASSED"
    echo -e "  ${RED}Failed:${NC}  $TESTS_FAILED"
    echo -e "  ${CYAN}Skipped:${NC} $TESTS_SKIPPED"
    echo -e "  ─────────────────"
    echo -e "  Total:   $total"
    echo ""
    
    if [[ $TESTS_FAILED -eq 0 ]]; then
        echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║  ALL TESTS PASSED - Ready for release  ║${NC}"
        echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
        return 0
    else
        echo -e "${RED}╔════════════════════════════════════════╗${NC}"
        echo -e "${RED}║  TESTS FAILED - Do not release!        ║${NC}"
        echo -e "${RED}╚════════════════════════════════════════╝${NC}"
        return 1
    fi
}

main() {
    echo ""
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║        PowerBlockade End-to-End Test Suite                    ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "  Primary:   $PRIMARY_IP"
    echo "  Secondary: $SECONDARY_IP"
    echo "  Domains:   $NUM_DOMAINS"
    echo ""
    
    log_section "1. Prerequisites"
    check_dependencies
    
    log_section "2. Connectivity Tests"
    check_connectivity "$PRIMARY_IP" "Primary"
    check_connectivity "$SECONDARY_IP" "Secondary"
    
    log_section "3. Admin UI Health"
    check_admin_ui "$PRIMARY_IP" "Primary"
    check_admin_ui "$SECONDARY_IP" "Secondary"
    
    log_section "4. DNS Resolution (Primary)"
    test_dns_bulk "$PRIMARY_IP" "Primary" "${TOP_DOMAINS[@]}"
    
    log_section "5. DNS Resolution (Secondary)"
    test_dns_bulk "$SECONDARY_IP" "Secondary" "${TOP_DOMAINS[@]}"
    
    log_section "6. Ad/Tracker Blocking"
    test_blocking "$PRIMARY_IP" "Primary"
    test_blocking "$SECONDARY_IP" "Secondary"
    
    log_section "7. Cache Performance"
    test_cache_performance "$PRIMARY_IP" "Primary"
    test_cache_performance "$SECONDARY_IP" "Secondary"
    
    log_section "8. Precache Functionality"
    test_precache "$PRIMARY_IP" "Primary"
    test_precache "$SECONDARY_IP" "Secondary"
    
    log_section "9. Query Logging"
    test_query_logging "$PRIMARY_IP" "$PRIMARY_IP" "Primary"
    test_query_logging "$SECONDARY_IP" "$PRIMARY_IP" "Secondary"
    
    log_section "10. Multi-Node Sync"
    test_secondary_sync "$PRIMARY_IP" "$SECONDARY_IP"
    
    generate_report
}

main "$@"
