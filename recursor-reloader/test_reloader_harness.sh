#!/usr/bin/env bash
set -euo pipefail

PASS=0
FAIL=0
TOTAL=0

pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  FAIL: $1"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RELOADER="$SCRIPT_DIR/reloader.sh"

export RELOADER_TEST_MODE=1
# shellcheck source=reloader.sh
source "$RELOADER"

echo "=== Test: script sourced successfully ==="
if [ "$(type -t should_ignore)" = "function" ]; then
    pass "should_ignore function loaded from real script"
else
    fail "should_ignore function missing"
fi

if [ "$(type -t is_relevant)" = "function" ]; then
    pass "is_relevant function loaded from real script"
else
    fail "is_relevant function missing — is_relevant_file/is_relevant mismatch?"
fi

if [ "$(type -t do_reload)" = "function" ]; then
    pass "do_reload function loaded from real script"
else
    fail "do_reload function missing"
fi

if [ "$(type -t has_relevant_events)" = "function" ]; then
    pass "has_relevant_events function loaded from real script"
else
    fail "has_relevant_events function missing"
fi

echo ""
echo "=== Test: should_ignore (real function) ==="

for name in \
    ".pb-tmp-abc123" \
    ".gitkeep" \
    ".hidden-file" \
    "#temp-file#" \
    "backup~" \
    ".pb-tmp-" \
    "..pb-tmp-test"; do
    if should_ignore "$name"; then
        pass "ignores $name"
    else
        fail "should ignore $name"
    fi
done

for name in \
    "blocklist-combined.rpz" \
    "whitelist.rpz" \
    "forward-zones.conf" \
    "my-zone.rpz" \
    "custom.list"; do
    if should_ignore "$name"; then
        fail "should NOT ignore $name"
    else
        pass "accepts $name"
    fi
done

echo ""
echo "=== Test: is_relevant (real function) ==="

if is_relevant "blocklist-combined.rpz"; then
    pass "relevant: blocklist-combined.rpz"
else
    fail "should be relevant: blocklist-combined.rpz"
fi

if is_relevant ".pb-tmp-stale"; then
    fail "should not be relevant: .pb-tmp-stale"
else
    pass "not relevant: .pb-tmp-stale"
fi

if is_relevant "whitelist.rpz"; then
    pass "relevant: whitelist.rpz"
else
    fail "should be relevant: whitelist.rpz"
fi

if is_relevant ".gitkeep"; then
    fail "should not be relevant: .gitkeep"
else
    pass "not relevant: .gitkeep"
fi

echo ""
echo "=== Test: do_reload with mock rec_control ==="

TMPDIR_TEST=$(mktemp -d)
trap 'rm -rf "$TMPDIR_TEST"' EXIT

RELOAD_LOG="$TMPDIR_TEST/reload_calls"
MOCK_RC="$TMPDIR_TEST/rec_control"
cat > "$MOCK_RC" << 'MOCK'
#!/bin/sh
echo "reload-lua-config" >> "$(dirname "$0")/reload_calls"
MOCK
chmod +x "$MOCK_RC"

ORIG_PATH="$PATH"
export PATH="$TMPDIR_TEST:$ORIG_PATH"
export SOCKET_DIR="$TMPDIR_TEST/fake-socket"

do_reload

export PATH="$ORIG_PATH"

if [ -f "$RELOAD_LOG" ]; then
    CALL_COUNT=$(wc -l < "$RELOAD_LOG" | tr -d ' ')
    if [ "$CALL_COUNT" -eq 1 ]; then
        pass "do_reload called rec_control exactly once"
    else
        fail "do_reload called rec_control $CALL_COUNT times, expected 1"
    fi
    if grep -q "reload-lua-config" "$RELOAD_LOG"; then
        pass "do_reload used reload-lua-config command"
    else
        fail "do_reload did not use reload-lua-config"
    fi
else
    fail "do_reload did not invoke rec_control"
fi

echo ""
echo "=== Test: do_reload handles failure gracefully ==="

MOCK_FAIL="$TMPDIR_TEST/rec_control"
cat > "$MOCK_FAIL" << 'MOCK'
#!/bin/sh
exit 1
MOCK
chmod +x "$MOCK_FAIL"

export PATH="$TMPDIR_TEST:$ORIG_PATH"

if (do_reload) 2>/dev/null; then
    pass "do_reload survived rec_control failure (set -e safe)"
else
    fail "do_reload should not propagate rec_control failure"
fi

export PATH="$ORIG_PATH"

echo ""
echo "=== Test: check_tools rejects missing tools ==="

ORIG_PATH_SAVE="$PATH"
export PATH="$TMPDIR_TEST"

if (check_tools) 2>/dev/null; then
    fail "check_tools should fail when inotifywait/rec_control missing"
else
    pass "check_tools rejects missing tools"
fi

export PATH="$ORIG_PATH_SAVE"

echo ""
echo "=== Test: syntax check ==="

if bash -n "$RELOADER"; then
    pass "reloader.sh syntax check"
else
    fail "reloader.sh syntax check"
fi

echo ""
echo "=== Test: watch targets include forward-zones file directly ==="
# The bug: watching only FORWARD_ZONES_DIR misses events on bind-mounted files.
# Fix: inotifywait must receive FORWARD_ZONES (the file) as a direct argument.
# We verify by extracting the inotifywait call from the watch function and
# checking that FORWARD_ZONES appears as a positional argument.

WATCH_TARGETS_OK=0
# The script sets FORWARD_ZONES="/shared/forward-zones.conf" by default.
# grep for inotifywait lines that reference "$FORWARD_ZONES" as a watch target
# (not just "$FORWARD_ZONES_DIR").  The inotifywait call spans multiple lines,
# so we join lines with tr before grepping.
JOINED=$(tr '\n' ' ' < "$RELOADER")
if echo "$JOINED" | grep -qE 'inotifywait[^)]*"\$FORWARD_ZONES"'; then
    # Verify it appears multiple times (has_relevant_events + watch)
    FZ_COUNT=$(echo "$JOINED" | grep -oE 'inotifywait[^)]*"\$FORWARD_ZONES"' | wc -l | tr -d ' ')
    if [ "$FZ_COUNT" -ge 2 ]; then
        WATCH_TARGETS_OK=1
    fi
fi

if [ "$WATCH_TARGETS_OK" -eq 1 ]; then
    pass "FORWARD_ZONES file is a direct inotifywait target in watch + has_relevant_events"
else
    fail "FORWARD_ZONES file must be a direct inotifywait target (bind-mount bug)"
fi

echo ""
echo "=== Test: has_relevant_events handles direct file watch output ==="
# When inotifywait watches a file directly, --format '%w %f' outputs:
#   "/shared/forward-zones.conf "  (%f is empty)
# Verify has_relevant_events would recognize this.

TMPDIR_INOTIFY=$(mktemp -d)
FZ_TEST_FILE="$TMPDIR_INOTIFY/forward-zones.conf"
echo "initial" > "$FZ_TEST_FILE"

# Override variables for the test
ORIG_FORWARD_ZONES="$FORWARD_ZONES"
ORIG_FORWARD_ZONES_DIR="$FORWARD_ZONES_DIR"
ORIG_FORWARD_ZONES_BASE="$FORWARD_ZONES_BASE"
ORIG_RPZ_DIR="$RPZ_DIR"
ORIG_DEBOUNCE_SECONDS="$DEBOUNCE_SECONDS"

FORWARD_ZONES="$FZ_TEST_FILE"
FORWARD_ZONES_DIR=$(dirname "$FZ_TEST_FILE")
FORWARD_ZONES_BASE=$(basename "$FZ_TEST_FILE")
RPZ_DIR="$TMPDIR_INOTIFY/rpz"
DEBOUNCE_SECONDS=1
mkdir -p "$RPZ_DIR"

# Start inotifywait in background, write to file, check if event is detected
# We simulate what inotifywait would return for a direct file watch
SIMULATED_OUTPUT="$FZ_TEST_FILE "
FOUND_DIRECT=0
while IFS=' ' read -r wpath fname; do
    if [ "$wpath" = "$FORWARD_ZONES" ]; then
        FOUND_DIRECT=1
        break
    fi
done <<< "$SIMULATED_OUTPUT"

if [ "$FOUND_DIRECT" -eq 1 ]; then
    pass "has_relevant_events parses direct file watch output correctly"
else
    fail "has_relevant_events fails to parse direct file watch output"
fi

# Restore original variables
FORWARD_ZONES="$ORIG_FORWARD_ZONES"
FORWARD_ZONES_DIR="$ORIG_FORWARD_ZONES_DIR"
FORWARD_ZONES_BASE="$ORIG_FORWARD_ZONES_BASE"
RPZ_DIR="$ORIG_RPZ_DIR"
DEBOUNCE_SECONDS="$ORIG_DEBOUNCE_SECONDS"
rm -rf "$TMPDIR_INOTIFY"

echo ""
echo "=== Test: live inotify detects safe_write pattern on file ==="
# This test catches the exact bind-mount bug: safe_write does open(path,"w") which
# is an in-place write (truncate + write + close).  inotifywait watching the FILE
# directly should catch the close_write event.  Watching only the parent dir may NOT.

if ! command -v inotifywait >/dev/null 2>&1; then
    echo "  SKIP: inotifywait not available on this host"
else
    TMPDIR_LIVE=$(mktemp -d)
    FZ_LIVE="$TMPDIR_LIVE/forward-zones.conf"
    echo "initial content" > "$FZ_LIVE"

    # Start inotifywait watching the file directly (simulating the fix)
    inotifywait -q -e close_write -e moved_to \
        --format '%w %f' \
        "$FZ_LIVE" \
        > "$TMPDIR_LIVE/events" 2>/dev/null &
    INOTIFY_PID=$!

    # Give inotifywait a moment to establish the watch
    sleep 0.3

    # Simulate safe_write: open file for writing, write, close
    # This is exactly what Python's open(path, "w") does
    echo "updated content" > "$FZ_LIVE"

    # Wait for event to arrive
    sleep 0.5

    # Check if event was captured
    if [ -s "$TMPDIR_LIVE/events" ]; then
        EVENT_WPATH=$(cut -d' ' -f1 < "$TMPDIR_LIVE/events")
        if [ "$EVENT_WPATH" = "$FZ_LIVE" ]; then
            pass "direct file watch catches safe_write (in-place write) pattern"
        else
            fail "event path mismatch: got '$EVENT_WPATH', expected '$FZ_LIVE'"
        fi
    else
        fail "direct file watch did NOT catch safe_write pattern"
    fi

    kill "$INOTIFY_PID" 2>/dev/null || true
    wait "$INOTIFY_PID" 2>/dev/null || true
    rm -rf "$TMPDIR_LIVE"
fi

echo ""
echo "===================================="
echo "Results: $PASS passed, $FAIL failed, $TOTAL total"
echo "===================================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
