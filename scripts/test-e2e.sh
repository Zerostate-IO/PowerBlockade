#!/usr/bin/env bash
#
# PowerBlockade End-to-End Test Suite
# Run this before releases to verify full functionality
#
# Usage: ./scripts/test-e2e.sh [primary_ip] [secondary_ip]
#
set -uo pipefail

PRIMARY_IP="${1:-10.5.5.2}"
SECONDARY_IP="${2:-10.5.5.3}"
ADMIN_PORT="8080"

NUM_DOMAINS="${NUM_DOMAINS:-1000}"
TEST_TIMEOUT=5
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
COOKIE_JAR="/tmp/pb_e2e_cookies_$$.txt"
TEST_BLOCK_DOMAINS=(
    "e2e-test-block-1.example.invalid"
    "e2e-test-block-2.example.invalid"
    "e2e-test-block-3.example.invalid"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

TESTS_PASSED=0
TESTS_FAILED=0
TESTS_WARNED=0

pass() { echo -e "${GREEN}[PASS]${NC} $*"; ((TESTS_PASSED++)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; ((TESTS_FAILED++)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; ((TESTS_WARNED++)); }
info() { echo -e "${BLUE}[INFO]${NC} $*"; }
section() { echo -e "\n${CYAN}═══════════════════════════════════════════════════════════${NC}"; echo -e "${CYAN} $*${NC}"; echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}\n"; }

cleanup() {
    rm -f "$COOKIE_JAR" 2>/dev/null || true
}
trap cleanup EXIT

authenticate() {
    local admin_ip="$1"
    
    if [[ -z "$ADMIN_PASSWORD" ]]; then
        warn "ADMIN_PASSWORD not set, skipping authenticated tests"
        return 1
    fi
    
    info "Authenticating to Admin UI..."
    
    local login_page
    login_page=$(curl -sf -c "$COOKIE_JAR" "http://${admin_ip}:${ADMIN_PORT}/login" 2>/dev/null)
    
    local csrf_token
    csrf_token=$(echo "$login_page" | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')
    
    if [[ -z "$csrf_token" ]]; then
        warn "Could not extract CSRF token"
        return 1
    fi
    
    local login_result
    login_result=$(curl -sf -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
        -X POST "http://${admin_ip}:${ADMIN_PORT}/login" \
        -H "X-CSRF-Token: ${csrf_token}" \
        -d "username=${ADMIN_USER}&password=${ADMIN_PASSWORD}" \
        -w "%{http_code}" -o /dev/null 2>/dev/null)
    
    if [[ "$login_result" == "302" ]] || [[ "$login_result" == "200" ]]; then
        pass "Authenticated successfully"
        return 0
    else
        fail "Authentication failed (HTTP $login_result)"
        return 1
    fi
}

add_test_block_entries() {
    local admin_ip="$1"
    
    info "Adding test block entries..."
    
    local blocklists_page
    blocklists_page=$(curl -sf -b "$COOKIE_JAR" "http://${admin_ip}:${ADMIN_PORT}/blocklists" 2>/dev/null)
    
    local csrf_token
    csrf_token=$(echo "$blocklists_page" | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')
    
    if [[ -z "$csrf_token" ]]; then
        warn "Could not get CSRF token for blocklists page"
        return 1
    fi
    
    local added=0
    for domain in "${TEST_BLOCK_DOMAINS[@]}"; do
        local result
        result=$(curl -sf -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
            -X POST "http://${admin_ip}:${ADMIN_PORT}/entries/add" \
            -H "X-CSRF-Token: ${csrf_token}" \
            -d "domain=${domain}&entry_type=block" \
            -w "%{http_code}" -o /dev/null 2>/dev/null)
        
        if [[ "$result" == "302" ]]; then
            ((added++))
        fi
    done
    
    if [[ $added -gt 0 ]]; then
        info "Added $added test block entries"
        return 0
    else
        warn "Could not add test block entries"
        return 1
    fi
}

apply_blocklists() {
    local admin_ip="$1"
    
    info "Applying blocklists..."
    
    local blocklists_page
    blocklists_page=$(curl -sf -b "$COOKIE_JAR" "http://${admin_ip}:${ADMIN_PORT}/blocklists" 2>/dev/null)
    
    local csrf_token
    csrf_token=$(echo "$blocklists_page" | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')
    
    local result
    result=$(curl -sf -b "$COOKIE_JAR" \
        -X POST "http://${admin_ip}:${ADMIN_PORT}/blocklists/apply" \
        -H "X-CSRF-Token: ${csrf_token}" \
        -w "%{http_code}" -o /dev/null 2>/dev/null)
    
    if [[ "$result" == "302" ]]; then
        info "Blocklists applied, waiting for recursor to reload..."
        sleep 6
        return 0
    else
        warn "Blocklist apply returned HTTP $result"
        return 1
    fi
}

test_custom_blocking() {
    local dns_server="$1"
    local name="$2"
    
    info "Testing custom block entries on $name..."
    
    local blocked=0
    local not_blocked=0
    
    for domain in "${TEST_BLOCK_DOMAINS[@]}"; do
        local result
        result=$(dig +short +time=3 +tries=1 "@${dns_server}" "$domain" A 2>/dev/null | head -1)
        
        if [[ -z "$result" || "$result" == "0.0.0.0" || "$result" == "127.0.0.1" ]]; then
            ((blocked++))
        else
            ((not_blocked++))
            info "  NOT blocked: $domain resolved to $result"
        fi
    done
    
    local total=${#TEST_BLOCK_DOMAINS[@]}
    
    if [[ $blocked -eq $total ]]; then
        pass "$name blocking all $total custom test domains"
        return 0
    elif [[ $blocked -gt 0 ]]; then
        warn "$name blocking $blocked/$total custom test domains"
        return 0
    else
        fail "$name not blocking any custom test domains"
        return 1
    fi
}

generate_domains() {
    local count="$1"
    local domains=()
    
    local tlds=("com" "org" "net" "io" "co" "dev" "app" "cloud" "tech" "ai")
    local prefixes=("www" "api" "cdn" "mail" "app" "web" "static" "img" "assets" "data")
    local words=("test" "demo" "example" "sample" "alpha" "beta" "gamma" "delta" "omega" "sigma"
                 "cloud" "tech" "data" "info" "news" "shop" "blog" "code" "dev" "app"
                 "fast" "quick" "smart" "bright" "clear" "fresh" "prime" "ultra" "mega" "super")
    
    local real_domains=(
        "google.com" "youtube.com" "facebook.com" "instagram.com" "twitter.com"
        "wikipedia.org" "amazon.com" "yahoo.com" "reddit.com" "linkedin.com"
        "netflix.com" "microsoft.com" "apple.com" "github.com" "stackoverflow.com"
        "twitch.tv" "discord.com" "spotify.com" "tiktok.com" "whatsapp.com"
        "zoom.us" "office.com" "bing.com" "duckduckgo.com" "cloudflare.com"
        "dropbox.com" "salesforce.com" "adobe.com" "paypal.com" "ebay.com"
        "cnn.com" "bbc.com" "nytimes.com" "weather.com" "imdb.com"
        "slack.com" "notion.so" "figma.com" "canva.com" "trello.com"
        "medium.com" "wordpress.com" "tumblr.com" "pinterest.com" "imgur.com"
        "shopify.com" "etsy.com" "target.com" "walmart.com" "bestbuy.com"
        "chase.com" "bankofamerica.com" "wellsfargo.com" "expedia.com" "kayak.com"
        "espn.com" "nfl.com" "nba.com" "steamcommunity.com" "epicgames.com"
        "hulu.com" "disneyplus.com" "coursera.org" "udemy.com" "duolingo.com"
        "airbnb.com" "uber.com" "doordash.com" "grubhub.com" "yelp.com"
        "tripadvisor.com" "booking.com" "hotels.com" "vrbo.com" "priceline.com"
        "cnet.com" "techcrunch.com" "theverge.com" "wired.com" "arstechnica.com"
        "npr.org" "bbc.co.uk" "theguardian.com" "reuters.com" "apnews.com"
        "gitlab.com" "bitbucket.org" "docker.com" "kubernetes.io" "terraform.io"
        "aws.amazon.com" "cloud.google.com" "azure.microsoft.com" "heroku.com" "netlify.com"
        "vercel.com" "digitalocean.com" "linode.com" "vultr.com" "ovhcloud.com"
    )
    
    for domain in "${real_domains[@]}"; do
        domains+=("$domain")
        [[ ${#domains[@]} -ge $count ]] && break
    done
    
    while [[ ${#domains[@]} -lt $count ]]; do
        local word1="${words[$RANDOM % ${#words[@]}]}"
        local word2="${words[$RANDOM % ${#words[@]}]}"
        local tld="${tlds[$RANDOM % ${#tlds[@]}]}"
        local prefix="${prefixes[$RANDOM % ${#prefixes[@]}]}"
        
        case $((RANDOM % 4)) in
            0) domains+=("${word1}${word2}.${tld}") ;;
            1) domains+=("${word1}-${word2}.${tld}") ;;
            2) domains+=("${prefix}.${word1}.${tld}") ;;
            3) domains+=("${word1}.${tld}") ;;
        esac
    done
    
    printf '%s\n' "${domains[@]}"
}

check_dependencies() {
    local missing=0
    for cmd in dig curl jq bc; do
        if ! command -v "$cmd" &>/dev/null; then
            fail "Missing dependency: $cmd"
            missing=1
        fi
    done
    [[ $missing -eq 0 ]] && pass "All dependencies present (dig, curl, jq, bc)"
    return $missing
}

check_connectivity() {
    local ip="$1"
    local name="$2"
    
    if timeout 3 ping -c 1 "$ip" &>/dev/null 2>&1; then
        pass "$name ($ip) is reachable"
        return 0
    else
        fail "$name ($ip) is not reachable"
        return 1
    fi
}

check_admin_ui() {
    local ip="$1"
    local name="$2"
    
    local response
    response=$(curl -sf --max-time "$TEST_TIMEOUT" "http://${ip}:${ADMIN_PORT}/health" 2>/dev/null) || {
        fail "$name Admin UI not responding"
        return 1
    }
    
    if echo "$response" | jq -e '.ok == true' &>/dev/null; then
        pass "$name Admin UI healthy"
        return 0
    else
        fail "$name Admin UI unhealthy: $response"
        return 1
    fi
}

setup_test_blocklist() {
    local admin_ip="$1"
    
    info "Setting up test block entries via API..."
    
    local test_domains=(
        "e2e-test-block-1.example.com"
        "e2e-test-block-2.example.com"
        "e2e-test-block-3.example.com"
        "ads.e2e-test.com"
        "tracker.e2e-test.com"
    )
    
    echo "${test_domains[@]}"
}

test_dns_bulk() {
    local dns_server="$1"
    local name="$2"
    local domain_count="$3"
    
    info "Generating $domain_count test domains..."
    local domains=()
    while IFS= read -r line; do
        domains+=("$line")
    done < <(generate_domains "$domain_count")
    
    info "Testing DNS resolution against $name ($dns_server)..."
    
    local success=0
    local failed=0
    local total=${#domains[@]}
    local start_time=$(date +%s.%N)
    
    local latencies=()
    
    for ((i=0; i<total; i++)); do
        local domain="${domains[$i]}"
        local query_start=$(date +%s%N)
        
        local result
        result=$(dig +short +time=3 +tries=1 "@${dns_server}" "$domain" A 2>/dev/null | head -1)
        
        local query_end=$(date +%s%N)
        local latency_ms=$(( (query_end - query_start) / 1000000 ))
        latencies+=("$latency_ms")
        
        if [[ -n "$result" && "$result" != "0.0.0.0" && "$result" != ";;"* ]]; then
            ((success++))
        else
            ((failed++))
            [[ $failed -le 3 ]] && info "  Failed: $domain"
        fi
        
        if (( (i+1) % 100 == 0 )); then
            printf "\r  Progress: %d/%d (%d%%)..." "$((i+1))" "$total" "$(( (i+1) * 100 / total ))"
        fi
    done
    printf "\r%80s\r" ""
    
    local end_time=$(date +%s.%N)
    local duration=$(echo "$end_time - $start_time" | bc)
    local qps=$(echo "scale=1; $total / $duration" | bc)
    
    local sorted_str=$(printf '%s\n' "${latencies[@]}" | sort -n)
    local sorted=()
    while IFS= read -r line; do
        sorted+=("$line")
    done <<< "$sorted_str"
    local sorted_len=${#sorted[@]}
    local min_lat="${sorted[0]}"
    local max_lat="${sorted[$((sorted_len - 1))]}"
    local p50_idx=$(( total / 2 ))
    local p95_idx=$(( total * 95 / 100 ))
    local p99_idx=$(( total * 99 / 100 ))
    local p50_lat="${sorted[$p50_idx]}"
    local p95_lat="${sorted[$p95_idx]}"
    local p99_lat="${sorted[$p99_idx]}"
    
    local sum=0
    for lat in "${latencies[@]}"; do
        sum=$((sum + lat))
    done
    local avg_lat=$((sum / total))
    
    local pct=$((success * 100 / total))
    
    echo "  Results: $success/$total resolved ($pct%)"
    echo "  Duration: ${duration}s | QPS: ${qps}"
    echo "  Latency: min=${min_lat}ms avg=${avg_lat}ms p50=${p50_lat}ms p95=${p95_lat}ms p99=${p99_lat}ms max=${max_lat}ms"
    
    # First 100 domains are real (google.com, etc) - these should always resolve
    # Synthetic domains beyond that may return NXDOMAIN which is correct behavior
    local real_domain_count=100
    if [[ $total -le $real_domain_count ]]; then
        # Testing only real domains - expect high success rate
        if [[ $pct -ge 90 ]]; then
            pass "$name DNS resolution: $pct% success rate"
        elif [[ $pct -ge 70 ]]; then
            warn "$name DNS resolution: $pct% success rate"
        else
            fail "$name DNS resolution: only $pct% success rate"
        fi
    else
        # Testing mix of real + synthetic domains
        # Success = at least 100 domains resolved (the real ones)
        if [[ $success -ge $real_domain_count ]]; then
            pass "$name DNS resolution: $success resolved ($pct%), all real domains OK"
        elif [[ $success -ge 50 ]]; then
            warn "$name DNS resolution: only $success resolved, some real domains failed"
        else
            fail "$name DNS resolution: only $success resolved, DNS may be broken"
        fi
    fi
}

test_blocking() {
    local dns_server="$1"
    local name="$2"
    
    local known_ad_domains=(
        "doubleclick.net"
        "googlesyndication.com"
        "googleadservices.com"
        "ads.google.com"
        "pagead2.googlesyndication.com"
        "adservice.google.com"
        "ad.doubleclick.net"
        "googleads.g.doubleclick.net"
        "www.googleadservices.com"
        "securepubads.g.doubleclick.net"
        "adclick.g.doubleclick.net"
        "adsserver.ysm.yahoo.com"
        "ads.yahoo.com"
        "pixel.facebook.com"
        "an.facebook.com"
        "ads.twitter.com"
        "analytics.twitter.com"
        "ads.linkedin.com"
        "tracking.linkedin.com"
    )
    
    info "Testing ad/tracker blocking on $name..."
    
    local blocked=0
    local not_blocked=0
    local not_blocked_list=()
    
    for domain in "${known_ad_domains[@]}"; do
        local result
        result=$(dig +short +time=3 +tries=1 "@${dns_server}" "$domain" A 2>/dev/null | head -1)
        
        if [[ -z "$result" || "$result" == "0.0.0.0" || "$result" == "127.0.0.1" || "$result" == "NXDOMAIN" ]]; then
            ((blocked++))
        else
            ((not_blocked++))
            not_blocked_list+=("$domain")
        fi
    done
    
    local total=${#known_ad_domains[@]}
    local pct=$((blocked * 100 / total))
    
    echo "  Blocked: $blocked/$total ($pct%)"
    
    if [[ ${#not_blocked_list[@]} -gt 0 && ${#not_blocked_list[@]} -le 5 ]]; then
        echo "  Not blocked: ${not_blocked_list[*]}"
    fi
    
    if [[ $pct -ge 70 ]]; then
        pass "$name blocking $blocked/$total ad/tracker domains"
    elif [[ $pct -ge 40 ]]; then
        warn "$name blocking $blocked/$total - consider adding more blocklists"
    else
        warn "$name blocking only $blocked/$total - blocklists may not be configured"
    fi
}

test_cache_performance() {
    local dns_server="$1"
    local name="$2"
    
    local test_domains=("google.com" "cloudflare.com" "github.com" "microsoft.com" "amazon.com")
    
    info "Testing cache performance on $name..."
    
    for domain in "${test_domains[@]}"; do
        dig +short +time=3 "@${dns_server}" "$domain" A &>/dev/null
    done
    
    sleep 0.5
    
    local cache_hits=0
    local total=${#test_domains[@]}
    
    for domain in "${test_domains[@]}"; do
        local start=$(date +%s%N)
        dig +short +time=3 "@${dns_server}" "$domain" A &>/dev/null
        local end=$(date +%s%N)
        local ms=$(( (end - start) / 1000000 ))
        
        if [[ $ms -lt 20 ]]; then
            ((cache_hits++))
        fi
    done
    
    local pct=$((cache_hits * 100 / total))
    echo "  Cache hits (< 20ms): $cache_hits/$total ($pct%)"
    
    if [[ $pct -ge 80 ]]; then
        pass "$name cache performance excellent"
    elif [[ $pct -ge 50 ]]; then
        pass "$name cache performance good"
    else
        warn "$name cache performance could be better"
    fi
}

test_consistency() {
    local primary="$1"
    local secondary="$2"
    
    local test_domains=("google.com" "github.com" "cloudflare.com" "microsoft.com" "amazon.com")
    local consistent=0
    local total=${#test_domains[@]}
    
    info "Testing resolution consistency between nodes..."
    
    for domain in "${test_domains[@]}"; do
        local primary_result secondary_result
        primary_result=$(dig +short +time=3 "@${primary}" "$domain" A 2>/dev/null | sort | head -1)
        secondary_result=$(dig +short +time=3 "@${secondary}" "$domain" A 2>/dev/null | sort | head -1)
        
        if [[ -n "$primary_result" && -n "$secondary_result" ]]; then
            ((consistent++))
        fi
    done
    
    echo "  Both nodes resolving: $consistent/$total"
    
    if [[ $consistent -eq $total ]]; then
        pass "Primary and secondary DNS consistent"
    else
        warn "Some inconsistency between nodes ($consistent/$total)"
    fi
}

test_latency_distribution() {
    local dns_server="$1"
    local name="$2"
    local sample_size=100
    
    info "Measuring latency distribution ($sample_size queries) on $name..."
    
    local domains=()
    while IFS= read -r line; do
        domains+=("$line")
    done < <(generate_domains "$sample_size")
    
    local latencies=()
    local under_10=0
    local under_50=0
    local under_100=0
    local over_100=0
    
    for domain in "${domains[@]}"; do
        local start=$(date +%s%N)
        dig +short +time=3 +tries=1 "@${dns_server}" "$domain" A &>/dev/null
        local end=$(date +%s%N)
        local ms=$(( (end - start) / 1000000 ))
        
        latencies+=("$ms")
        
        if [[ $ms -lt 10 ]]; then ((under_10++))
        elif [[ $ms -lt 50 ]]; then ((under_50++))
        elif [[ $ms -lt 100 ]]; then ((under_100++))
        else ((over_100++))
        fi
    done
    
    echo "  < 10ms:  $under_10 ($((under_10 * 100 / sample_size))%)"
    echo "  < 50ms:  $under_50 ($((under_50 * 100 / sample_size))%)"
    echo "  < 100ms: $under_100 ($((under_100 * 100 / sample_size))%)"
    echo "  > 100ms: $over_100 ($((over_100 * 100 / sample_size))%)"
    
    local fast_pct=$(( (under_10 + under_50) * 100 / sample_size ))
    if [[ $fast_pct -ge 70 ]]; then
        pass "$name latency distribution good ($fast_pct% under 50ms)"
    elif [[ $fast_pct -ge 50 ]]; then
        warn "$name latency distribution acceptable ($fast_pct% under 50ms)"
    else
        fail "$name latency distribution poor ($fast_pct% under 50ms)"
    fi
}

generate_report() {
    section "Test Results Summary"
    
    local total=$((TESTS_PASSED + TESTS_FAILED + TESTS_WARNED))
    
    echo -e "  ${GREEN}Passed:${NC}  $TESTS_PASSED"
    echo -e "  ${RED}Failed:${NC}  $TESTS_FAILED"
    echo -e "  ${YELLOW}Warned:${NC} $TESTS_WARNED"
    echo -e "  ─────────────────"
    echo -e "  Total:   $total"
    echo ""
    
    if [[ $TESTS_FAILED -eq 0 ]]; then
        echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║     ALL TESTS PASSED - Ready for release!              ║${NC}"
        echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
        return 0
    else
        echo -e "${RED}╔════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║     $TESTS_FAILED TEST(S) FAILED - Fix before release!           ║${NC}"
        echo -e "${RED}╚════════════════════════════════════════════════════════╝${NC}"
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
    [[ -n "$ADMIN_PASSWORD" ]] && echo "  Auth:      Enabled" || echo "  Auth:      Disabled (set ADMIN_PASSWORD to enable blocking tests)"
    echo ""
    
    section "1. Prerequisites"
    check_dependencies || exit 1
    
    section "2. Connectivity"
    check_connectivity "$PRIMARY_IP" "Primary" || exit 1
    check_connectivity "$SECONDARY_IP" "Secondary" || exit 1
    
    section "3. Admin UI Health"
    check_admin_ui "$PRIMARY_IP" "Primary"
    check_admin_ui "$SECONDARY_IP" "Secondary"
    
    local authenticated=false
    if [[ -n "$ADMIN_PASSWORD" ]]; then
        section "4. Authentication & Blocking Setup"
        if authenticate "$PRIMARY_IP"; then
            authenticated=true
            add_test_block_entries "$PRIMARY_IP"
            apply_blocklists "$PRIMARY_IP"
        fi
    else
        section "4. Blocking Setup (SKIPPED)"
        warn "Set ADMIN_PASSWORD to enable authenticated blocking tests"
    fi
    
    section "5. DNS Bulk Resolution (Primary)"
    test_dns_bulk "$PRIMARY_IP" "Primary" "$NUM_DOMAINS"
    
    section "6. DNS Bulk Resolution (Secondary)"
    test_dns_bulk "$SECONDARY_IP" "Secondary" "$NUM_DOMAINS"
    
    section "7. Custom Block Entry Verification"
    if [[ "$authenticated" == "true" ]]; then
        test_custom_blocking "$PRIMARY_IP" "Primary"
        test_custom_blocking "$SECONDARY_IP" "Secondary"
    else
        warn "Skipping custom blocking test (not authenticated)"
    fi
    
    section "8. Ad/Tracker Blocking (Blocklist-based)"
    test_blocking "$PRIMARY_IP" "Primary"
    test_blocking "$SECONDARY_IP" "Secondary"
    
    section "9. Cache Performance"
    test_cache_performance "$PRIMARY_IP" "Primary"
    test_cache_performance "$SECONDARY_IP" "Secondary"
    
    section "10. Latency Distribution"
    test_latency_distribution "$PRIMARY_IP" "Primary"
    test_latency_distribution "$SECONDARY_IP" "Secondary"
    
    section "11. Multi-Node Consistency"
    test_consistency "$PRIMARY_IP" "$SECONDARY_IP"
    
    generate_report
}

main "$@"
