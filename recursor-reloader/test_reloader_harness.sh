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
echo "===================================="
echo "Results: $PASS passed, $FAIL failed, $TOTAL total"
echo "===================================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
