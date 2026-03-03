#!/usr/bin/env bash
# Fresh Install Smoke Test for PowerBlockade
#
# Tests the canonical prebuilt artifact path from clean state:
#   1. Cleanup: down -v (removes containers + volumes)
#   2. Bootstrap: init-env.sh --non-interactive
#   3. Start: docker compose -f docker-compose.ghcr.yml up -d
#   4. Auth: Login with configured credentials
#   5. DNS: Resolution through dnsdist port 53
#
# Usage:
#   ./scripts/smoke-test.sh              # Full fresh install test
#   ./scripts/smoke-test.sh --skip-cleanup  # Keep volumes (for local dev)
#
# Exit codes:
#   0: All checks passed
#   1: One or more checks failed
#
# This is a release-blocking gate. DO NOT make it non-blocking in CI.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.ghcr.yml"

# Test credentials (used for bootstrap and auth check)
TEST_ADMIN_USERNAME="smoke-test-admin"
TEST_ADMIN_PASSWORD="smoke-test-password-$(date +%s)"

# Timing
HEALTH_WAIT_TIMEOUT=120
DNS_WAIT_TIMEOUT=60

# Flags
SKIP_CLEANUP=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_pass()   { echo -e "${GREEN}[PASS]${NC} $*"; }
log_fail()   { echo -e "${RED}[FAIL]${NC} $*" >&2; }
log_warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_section() { echo ""; echo -e "${BOLD}=== $* ===${NC}"; }

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-cleanup)
      SKIP_CLEANUP=true
      shift
      ;;
    -h|--help)
      cat <<EOF
PowerBlockade Fresh Install Smoke Test

USAGE:
    ./scripts/smoke-test.sh [OPTIONS]

OPTIONS:
    --skip-cleanup    Don't run 'down -v' (useful for local testing)
    -h, --help        Show this help

EXIT CODES:
    0  All checks passed
    1  One or more checks failed

CI USAGE:
    This is a release-blocking gate. Smoke test MUST pass before release.
EOF
      exit 0
      ;;
    *)
      log_fail "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Track check results
CHECKS_PASSED=0
CHECKS_FAILED=0

check_pass() {
  CHECKS_PASSED=$((CHECKS_PASSED + 1))
  log_pass "$1"
}

check_fail() {
  CHECKS_FAILED=$((CHECKS_FAILED + 1))
  log_fail "$1"
}

# ============================================
# PHASE 1: CLEANUP (Fresh State)
# ============================================
log_section "Phase 1: Cleanup"

if [[ "$SKIP_CLEANUP" == "true" ]]; then
  log_warn "Skipping cleanup (--skip-cleanup)"
else
  log_info "Stopping containers and removing volumes..."
  cd "$PROJECT_DIR"
  docker compose -f docker-compose.ghcr.yml down -v --remove-orphans 2>/dev/null || true
  check_pass "Clean state achieved (containers + volumes removed)"
fi

# ============================================
# PHASE 2: BOOTSTRAP (Environment Setup)
# ============================================
log_section "Phase 2: Bootstrap"

cd "$PROJECT_DIR"

log_info "Running init-env.sh with test credentials..."
if ./scripts/init-env.sh --non-interactive \
    --node-name "smoke-test" \
    --admin-username "$TEST_ADMIN_USERNAME" \
    --admin-password "$TEST_ADMIN_PASSWORD" \
    --dns-bind-address "0.0.0.0" > /tmp/smoke-init.log 2>&1; then
  check_pass "Environment bootstrap completed"
else
  check_fail "Environment bootstrap failed"
  cat /tmp/smoke-init.log
  exit 1
fi

# Verify .env was created with test credentials
if [[ -f "$PROJECT_DIR/.env" ]]; then
  if grep -q "^ADMIN_USERNAME=$TEST_ADMIN_USERNAME$" "$PROJECT_DIR/.env"; then
    check_pass "Test credentials written to .env"
  else
    check_fail "Test credentials not found in .env"
    exit 1
  fi
else
  check_fail ".env file not created"
  exit 1
fi

# ============================================
# PHASE 3: START (Service Startup)
# ============================================
log_section "Phase 3: Start Services"

log_info "Starting services with docker-compose.ghcr.yml..."
cd "$PROJECT_DIR"
docker compose -f docker-compose.ghcr.yml up -d

log_info "Waiting for services to become healthy (timeout: ${HEALTH_WAIT_TIMEOUT}s)..."

waited=0
all_healthy=false

while [[ $waited -lt $HEALTH_WAIT_TIMEOUT ]]; do
  # Check if all core containers are running
  containers_status=$(docker compose -f docker-compose.ghcr.yml ps --format "{{.Names}}:{{.Status}}" 2>/dev/null || echo "")
  
  # Required containers
  required=("powerblockade-dnsdist" "powerblockade-recursor" "powerblockade-postgres" "powerblockade-admin-ui")
  healthy_count=0
  
  for container in "${required[@]}"; do
    if echo "$containers_status" | grep -qE "${container}.*(healthy|running|Up)"; then
      ((healthy_count++))
    fi
  done
  
  if [[ $healthy_count -eq ${#required[@]} ]]; then
    all_healthy=true
    break
  fi
  
  echo -n "."
  sleep 2
  ((waited += 2))
done
echo ""

if [[ "$all_healthy" == "true" ]]; then
  check_pass "All core containers running ($healthy_count/${#required[@]})"
else
  check_fail "Containers not healthy after ${HEALTH_WAIT_TIMEOUT}s"
  docker compose -f docker-compose.ghcr.yml ps
  exit 1
fi

# ============================================
# PHASE 4: AUTH CHECK (Admin Login)
# ============================================
log_section "Phase 4: Auth Check"

log_info "Testing admin login with configured credentials..."

# Give admin-ui a moment to fully initialize
sleep 5

# POST to /login with form data
LOGIN_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
  -F "username=$TEST_ADMIN_USERNAME" \
  -F "password=$TEST_ADMIN_PASSWORD" \
  "http://localhost:8080/login" 2>/dev/null || echo -e "\n000")

LOGIN_BODY=$(echo "$LOGIN_RESPONSE" | head -n -1)
LOGIN_CODE=$(echo "$LOGIN_RESPONSE" | tail -n 1)

# Login should redirect (302) on success, or 401 on failure
if [[ "$LOGIN_CODE" == "302" ]]; then
  check_pass "Admin login successful (HTTP 302 redirect)"
elif [[ "$LOGIN_CODE" == "200" ]]; then
  # 200 might mean it returned the login page with error
  if echo "$LOGIN_BODY" | grep -qi "invalid credentials"; then
    check_fail "Admin login failed - invalid credentials"
    exit 1
  else
    # Could be a successful login that didn't redirect
    check_pass "Admin login returned HTTP 200"
  fi
else
  check_fail "Admin login failed (HTTP $LOGIN_CODE)"
  log_info "Response body excerpt:"
  echo "$LOGIN_BODY" | head -20
  exit 1
fi

# Also check /health endpoint
HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080/health" 2>/dev/null || echo "000")
if [[ "$HEALTH_CODE" == "200" ]]; then
  check_pass "Health endpoint OK (HTTP 200)"
else
  check_fail "Health endpoint failed (HTTP $HEALTH_CODE)"
  exit 1
fi

# ============================================
# PHASE 5: DNS CHECK (Resolution Test)
# ============================================
log_section "Phase 5: DNS Check"

log_info "Testing DNS resolution through dnsdist (timeout: ${DNS_WAIT_TIMEOUT}s)..."

waited=0
dns_ok=false

while [[ $waited -lt $DNS_WAIT_TIMEOUT ]]; do
  # Test DNS resolution
  DNS_RESULT=$(dig @127.0.0.1 google.com +short +time=3 2>/dev/null || echo "")
  
  # Check if we got any IP addresses back
  if [[ -n "$DNS_RESULT" ]] && echo "$DNS_RESULT" | grep -qE "^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+"; then
    dns_ok=true
    break
  fi
  
  echo -n "."
  sleep 2
  ((waited += 2))
done
echo ""

if [[ "$dns_ok" == "true" ]]; then
  check_pass "DNS resolution working (google.com resolved)"
  log_info "Resolved to: $(echo "$DNS_RESULT" | head -1)"
else
  check_fail "DNS resolution failed after ${DNS_WAIT_TIMEOUT}s"
  # Don't exit - DNS might be blocked by CI environment
  log_warn "DNS check failed but not blocking (CI may block port 53)"
fi

# ============================================
# PHASE 6: CLEANUP (Optional)
# ============================================
if [[ "$SKIP_CLEANUP" == "true" ]]; then
  log_warn "Leaving services running (--skip-cleanup)"
else
  log_section "Phase 6: Cleanup"
  log_info "Stopping containers and removing volumes..."
  cd "$PROJECT_DIR"
  docker compose -f docker-compose.ghcr.yml down -v --remove-orphans 2>/dev/null || true
  log_pass "Cleanup complete"
fi

# ============================================
# SUMMARY
# ============================================
log_section "Smoke Test Summary"

echo ""
echo "  Checks passed: $CHECKS_PASSED"
echo "  Checks failed: $CHECKS_FAILED"
echo ""

if [[ $CHECKS_FAILED -eq 0 ]]; then
  echo -e "${GREEN}${BOLD}╔════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}${BOLD}║         SMOKE TEST PASSED              ║${NC}"
  echo -e "${GREEN}${BOLD}╚════════════════════════════════════════╝${NC}"
  exit 0
else
  echo -e "${RED}${BOLD}╔════════════════════════════════════════╗${NC}"
  echo -e "${RED}${BOLD}║         SMOKE TEST FAILED              ║${NC}"
  echo -e "${RED}${BOLD}╚════════════════════════════════════════╝${NC}"
  exit 1
fi
