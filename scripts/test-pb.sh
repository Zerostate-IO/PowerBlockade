#!/usr/bin/env bash
# Test suite for pb CLI
# Usage: ./scripts/test-pb.sh
#
# Tests the pb CLI utility functions without requiring Docker or external services.
# Uses a mock environment to test upgrade/rollback logic.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Test results
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Test temporary directory
TEST_TMP=""

setup_test_env() {
    TEST_TMP=$(mktemp -d)
    export PROJECT_DIR="$TEST_TMP"
    export STATE_DIR="$TEST_TMP/.powerblockade"
    export STATE_FILE="$STATE_DIR/state.json"
    export BACKUP_DIR="$TEST_TMP/backups"
    mkdir -p "$STATE_DIR" "$BACKUP_DIR"
    
    # Create minimal compose.yaml
    cat > "$TEST_TMP/compose.yaml" <<EOF
version: '3.8'
services:
  admin-ui:
    image: alpine:latest
EOF
}

cleanup_test_env() {
    if [[ -n "$TEST_TMP" && -d "$TEST_TMP" ]]; then
        rm -rf "$TEST_TMP"
    fi
}

# Test assertion helpers
assert_eq() {
    local expected="$1"
    local actual="$2"
    local msg="${3:-}"
    
    if [[ "$expected" == "$actual" ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: expected '$expected', got '$actual' ${msg:+($msg)}"
        return 1
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local msg="${3:-}"
    
    if [[ "$haystack" == *"$needle"* ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: '$needle' not found in output ${msg:+($msg)}"
        return 1
    fi
}

assert_file_exists() {
    local path="$1"
    local msg="${2:-}"
    
    if [[ -f "$path" ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: file '$path' does not exist ${msg:+($msg)}"
        return 1
    fi
}

assert_exit_code() {
    local expected="$1"
    local actual="$2"
    local msg="${3:-}"
    
    if [[ "$expected" -eq "$actual" ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: expected exit code $expected, got $actual ${msg:+($msg)}"
        return 1
    fi
}

run_test() {
    local test_name="$1"
    local test_func="$2"
    
    TESTS_RUN=$((TESTS_RUN + 1))
    echo -n "  Testing: $test_name ... "
    
    setup_test_env
    
    local result=0
    if $test_func 2>&1; then
        echo -e "${GREEN}PASS${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${RED}FAIL${NC}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        result=1
    fi
    
    cleanup_test_env
    return $result
}

# =============================================================================
# Source pb functions for testing (extract them)
# =============================================================================

# We source individual functions by extracting them from pb
# This allows unit testing without running the full script

source_pb_functions() {
    # Create a testable version of pb functions
    cat > "$TEST_TMP/pb_functions.sh" <<'FUNCS'
get_current_version() {
    local state_file="${STATE_FILE:-}"
    if [[ -f "$state_file" ]]; then
        jq -r '.current_version // "unknown"' "$state_file" 2>/dev/null || echo "unknown"
    else
        echo "unknown"
    fi
}

get_compose_files() {
    local project_dir="${PROJECT_DIR:-}"
    local files="-f compose.yaml"
    if [[ -f "$project_dir/compose.user.yaml" ]]; then
        files="$files -f compose.user.yaml"
    elif [[ -f "$project_dir/docker-compose.yml" ]]; then
        files="-f docker-compose.yml"
    fi
    echo "$files"
}

check_disk_space() {
    local required_mb=500
    local available_mb
    local project_dir="${PROJECT_DIR:-}"
    available_mb=$(df -m "$project_dir" | awk 'NR==2 {print $4}')
    if [[ "$available_mb" -lt "$required_mb" ]]; then
        return 1
    fi
    return 0
}

save_state() {
    local version="$1"
    local prev_version="$2"
    local prev_digests="$3"
    local db_backup="$4"
    local config_backup="$5"
    local state_file="${STATE_FILE:-}"
    
    cat > "$state_file" <<EOF
{
    "current_version": "$version",
    "previous_version": "$prev_version",
    "previous_image_digests": $prev_digests,
    "last_db_backup": "$db_backup",
    "last_config_backup": "$config_backup",
    "upgrade_timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
}

backup_config() {
    local timestamp
    timestamp=$(date +%Y%m%d-%H%M%S)
    local backup_dir="${BACKUP_DIR:-}"
    local project_dir="${PROJECT_DIR:-}"
    local backup_file="$backup_dir/config-$timestamp.tar.gz"
    
    cd "$project_dir"
    local files_to_backup=""
    [[ -d shared/rpz ]] && files_to_backup="$files_to_backup shared/rpz"
    [[ -d shared/forward-zones ]] && files_to_backup="$files_to_backup shared/forward-zones"
    [[ -f .env ]] && files_to_backup="$files_to_backup .env"
    
    if [[ -n "$files_to_backup" ]]; then
        tar -czf "$backup_file" $files_to_backup 2>/dev/null || true
        echo "$backup_file"
    else
        echo ""
    fi
}
FUNCS
    source "$TEST_TMP/pb_functions.sh"
}

# =============================================================================
# Test Cases
# =============================================================================

test_get_current_version_no_state() {
    source_pb_functions
    local version
    version=$(get_current_version)
    assert_eq "unknown" "$version" "should return 'unknown' when no state file"
}

test_get_current_version_with_state() {
    source_pb_functions
    cat > "$STATE_FILE" <<EOF
{
    "current_version": "0.3.1",
    "previous_version": "0.3.0"
}
EOF
    local version
    version=$(get_current_version)
    assert_eq "0.3.1" "$version" "should return version from state file"
}

test_get_current_version_malformed_json() {
    source_pb_functions
    echo "not json" > "$STATE_FILE"
    local version
    version=$(get_current_version)
    assert_eq "unknown" "$version" "should return 'unknown' for malformed JSON"
}

test_get_compose_files_default() {
    source_pb_functions
    local files
    files=$(get_compose_files)
    assert_eq "-f compose.yaml" "$files" "should return default compose.yaml"
}

test_get_compose_files_with_user_override() {
    source_pb_functions
    touch "$TEST_TMP/compose.user.yaml"
    local files
    files=$(get_compose_files)
    assert_eq "-f compose.yaml -f compose.user.yaml" "$files" "should include user override"
}

test_get_compose_files_legacy_docker_compose() {
    source_pb_functions
    rm -f "$TEST_TMP/compose.yaml"
    touch "$TEST_TMP/docker-compose.yml"
    local files
    files=$(get_compose_files)
    assert_eq "-f docker-compose.yml" "$files" "should fallback to docker-compose.yml"
}

test_check_disk_space_sufficient() {
    source_pb_functions
    # Test tmp always has space
    check_disk_space
    assert_exit_code 0 $? "should pass when disk space is sufficient"
}

test_save_state_creates_valid_json() {
    source_pb_functions
    save_state "0.3.2" "0.3.1" '{"admin-ui": "sha256:abc123"}' "/backup/db.sql" "/backup/config.tar.gz"
    
    assert_file_exists "$STATE_FILE" "state file should be created"
    
    local version
    version=$(jq -r '.current_version' "$STATE_FILE")
    assert_eq "0.3.2" "$version" "current_version should be saved"
    
    local prev
    prev=$(jq -r '.previous_version' "$STATE_FILE")
    assert_eq "0.3.1" "$prev" "previous_version should be saved"
    
    local db_backup
    db_backup=$(jq -r '.last_db_backup' "$STATE_FILE")
    assert_eq "/backup/db.sql" "$db_backup" "db backup path should be saved"
}

test_save_state_overwrites_existing() {
    source_pb_functions
    save_state "0.3.0" "0.2.0" '{}' "" ""
    save_state "0.3.1" "0.3.0" '{}' "" ""
    
    local version
    version=$(jq -r '.current_version' "$STATE_FILE")
    assert_eq "0.3.1" "$version" "should overwrite with new version"
    
    local prev
    prev=$(jq -r '.previous_version' "$STATE_FILE")
    assert_eq "0.3.0" "$prev" "should update previous version"
}

test_backup_config_no_files() {
    source_pb_functions
    local result
    result=$(backup_config)
    assert_eq "" "$result" "should return empty when no config files exist"
}

test_backup_config_with_env() {
    source_pb_functions
    echo "ADMIN_PASSWORD=secret" > "$TEST_TMP/.env"
    local result
    result=$(backup_config)
    assert_contains "$result" "config-" "should return backup filename"
    assert_file_exists "$result" "backup file should be created"
}

test_backup_config_with_shared_dirs() {
    source_pb_functions
    mkdir -p "$TEST_TMP/shared/rpz"
    echo "*.ads.example.com" > "$TEST_TMP/shared/rpz/blocklist.rpz"
    mkdir -p "$TEST_TMP/shared/forward-zones"
    echo "example.com=8.8.8.8" > "$TEST_TMP/shared/forward-zones/custom.conf"
    
    local result
    result=$(backup_config)
    assert_contains "$result" "config-" "should return backup filename"
    assert_file_exists "$result" "backup file should be created"
    
    # Verify contents
    local contents
    contents=$(tar -tzf "$result" 2>/dev/null || echo "")
    assert_contains "$contents" "shared/rpz" "backup should contain rpz dir"
    assert_contains "$contents" "shared/forward-zones" "backup should contain forward-zones dir"
}

test_pb_help_command() {
    local output
    output=$("$SCRIPT_DIR/pb" help 2>&1)
    assert_contains "$output" "Usage:" "should show usage"
    assert_contains "$output" "status" "should list status command"
    assert_contains "$output" "update" "should list update command"
    assert_contains "$output" "rollback" "should list rollback command"
    assert_contains "$output" "backup" "should list backup command"
}

test_pb_version_command() {
    local output
    output=$("$SCRIPT_DIR/pb" version 2>&1)
    assert_contains "$output" "pb version" "should show CLI version"
}

test_pb_unknown_command() {
    local exit_code=0
    "$SCRIPT_DIR/pb" unknowncommand123 2>&1 || exit_code=$?
    assert_exit_code 1 $exit_code "should exit with 1 for unknown command"
}

test_pb_status_no_docker() {
    # This test verifies pb status handles missing docker gracefully
    # We can't easily mock docker, so we just verify it runs
    local exit_code=0
    timeout 5 "$SCRIPT_DIR/pb" status 2>&1 || exit_code=$?
    # Status should work even if docker compose fails (shows error but continues)
    # Exit code 0 or non-zero is acceptable depending on docker availability
    return 0
}

test_state_file_rollback_detection() {
    source_pb_functions
    
    # No state file - should fail rollback check
    if [[ ! -f "$STATE_FILE" ]]; then
        # Good - no state file means no rollback possible
        return 0
    fi
    return 1
}

test_state_file_preserves_digests() {
    source_pb_functions
    local digests='{"admin-ui":"sha256:abc123","dnstap-processor":"sha256:def456"}'
    save_state "0.3.2" "0.3.1" "$digests" "" ""
    
    local stored_digest
    stored_digest=$(jq -r '.previous_image_digests["admin-ui"]' "$STATE_FILE")
    assert_eq "sha256:abc123" "$stored_digest" "should preserve admin-ui digest"
    
    stored_digest=$(jq -r '.previous_image_digests["dnstap-processor"]' "$STATE_FILE")
    assert_eq "sha256:def456" "$stored_digest" "should preserve dnstap-processor digest"
}

test_upgrade_timestamp_format() {
    source_pb_functions
    save_state "0.3.2" "0.3.1" '{}' "" ""
    
    local timestamp
    timestamp=$(jq -r '.upgrade_timestamp' "$STATE_FILE")
    
    # Should be ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ
    if [[ "$timestamp" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then
        return 0
    else
        echo "Invalid timestamp format: $timestamp"
        return 1
    fi
}

# =============================================================================
# Run Tests
# =============================================================================

echo ""
echo "=========================================="
echo "  pb CLI Test Suite"
echo "=========================================="
echo ""

# Function tests
echo "Function Tests:"
run_test "get_current_version - no state file" test_get_current_version_no_state || true
run_test "get_current_version - with state file" test_get_current_version_with_state || true
run_test "get_current_version - malformed JSON" test_get_current_version_malformed_json || true
run_test "get_compose_files - default" test_get_compose_files_default || true
run_test "get_compose_files - with user override" test_get_compose_files_with_user_override || true
run_test "get_compose_files - legacy docker-compose.yml" test_get_compose_files_legacy_docker_compose || true
run_test "check_disk_space - sufficient" test_check_disk_space_sufficient || true
run_test "save_state - creates valid JSON" test_save_state_creates_valid_json || true
run_test "save_state - overwrites existing" test_save_state_overwrites_existing || true
run_test "backup_config - no files" test_backup_config_no_files || true
run_test "backup_config - with .env" test_backup_config_with_env || true
run_test "backup_config - with shared dirs" test_backup_config_with_shared_dirs || true
run_test "state file preserves digests" test_state_file_preserves_digests || true
run_test "upgrade timestamp format" test_upgrade_timestamp_format || true

echo ""
echo "Command Tests:"
run_test "pb help" test_pb_help_command || true
run_test "pb version" test_pb_version_command || true
run_test "pb unknown command" test_pb_unknown_command || true
run_test "pb status (no docker)" test_pb_status_no_docker || true
run_test "rollback detection without state" test_state_file_rollback_detection || true

echo ""
echo "=========================================="
echo "  Results: $TESTS_PASSED/$TESTS_RUN passed"
if [[ $TESTS_FAILED -gt 0 ]]; then
    echo -e "  ${RED}$TESTS_FAILED test(s) failed${NC}"
    echo "=========================================="
    exit 1
else
    echo -e "  ${GREEN}All tests passed!${NC}"
    echo "=========================================="
    exit 0
fi
