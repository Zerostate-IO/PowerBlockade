#!/usr/bin/env bash
# recursor-reloader: inotify watcher sidecar for PowerBlockade
#
# Contract:
#   - IN_CLOSE_WRITE + MOVED_TO for completed file changes
#   - Filters out temp/dotfile noise (.pb-tmp-*, .gitkeep, etc.)
#   - Debounces rapid multi-file updates into a single reload cycle
#   - Waits for rec_control ping before serving events
#   - Uses rec_control reload-lua-config as the single reload command
#
set -euo pipefail

SOCKET_DIR="${RELOADER_SOCKET_DIR:-/var/run/pdns-recursor}"
RPZ_DIR="${RELOADER_RPZ_DIR:-/shared/rpz}"
FORWARD_ZONES="${RELOADER_FORWARD_ZONES:-/shared/forward-zones.conf}"
DEBOUNCE_SECONDS="${RELOADER_DEBOUNCE_SECONDS:-2}"
PING_RETRY_INTERVAL="${RELOADER_PING_RETRY_INTERVAL:-5}"
PING_MAX_ATTEMPTS="${RELOADER_PING_MAX_ATTEMPTS:-60}"
IGNORE_PATTERN='\.pb-tmp-|\.gitkeep|^\.|^#|~$'

# Watch the parent directory for forward-zones.conf to survive atomic replaces
FORWARD_ZONES_DIR=$(dirname "$FORWARD_ZONES")
FORWARD_ZONES_BASE=$(basename "$FORWARD_ZONES")

log() {
    echo "$(date +%FT%T) recursor-reloader: $*"
}

err() {
    echo "$(date +%FT%T) recursor-reloader ERROR: $*" >&2
}

check_tools() {
    local missing=0
    for tool in inotifywait rec_control; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            err "required tool not found: $tool"
            missing=1
        fi
    done
    if [ "$missing" -eq 1 ]; then
        err "aborting: missing required tools"
        exit 1
    fi
    log "tool check passed: inotifywait and rec_control available"
}

wait_for_recursor() {
    local attempt=0
    log "waiting for recursor to respond to ping (socket-dir=$SOCKET_DIR)"
    while [ "$attempt" -lt "$PING_MAX_ATTEMPTS" ]; do
        if rec_control --socket-dir="$SOCKET_DIR" ping 2>/dev/null | grep -qi pong; then
            log "recursor is ready"
            return 0
        fi
        attempt=$((attempt + 1))
        log "ping attempt $attempt/$PING_MAX_ATTEMPTS failed, retrying in ${PING_RETRY_INTERVAL}s..."
        sleep "$PING_RETRY_INTERVAL"
    done
    err "recursor did not respond after $PING_MAX_ATTEMPTS attempts"
    exit 1
}

do_reload() {
    log "triggering reload-lua-config"
    if rec_control --socket-dir="$SOCKET_DIR" reload-lua-config 2>&1; then
        log "reload-lua-config succeeded"
    else
        local rc=$?
        err "reload-lua-config failed (exit code $rc)"
    fi
}

should_ignore() {
    local filename="$1"
    local base="${filename##*/}"
    [ -z "$base" ] && return 0
    if echo "$base" | grep -qE "$IGNORE_PATTERN"; then
        return 0
    fi
    return 1
}

is_relevant() {
    local filename="$1"
    should_ignore "$filename" && return 1
    return 0
}

has_relevant_events() {
    # Non-blocking drain: wait up to DEBOUNCE_SECONDS for more events.
    # Returns 0 (true) if events arrived, 1 (false) if timed out.
    local output
    output=$(inotifywait -q -r \
        -e close_write -e moved_to \
        --format '%w %f' \
        -t "$DEBOUNCE_SECONDS" \
        "$RPZ_DIR" "$FORWARD_ZONES_DIR" 2>/dev/null) || return 1

    # Check if any of the events are for relevant files
    local found_relevant=1
    while IFS=' ' read -r wpath fname; do
        # For forward-zones dir events, only care about the forward-zones file
        if [ "$wpath" = "$FORWARD_ZONES_DIR/" ]; then
            [ "$fname" = "$FORWARD_ZONES_BASE" ] || continue
        fi
        if is_relevant "$fname"; then
            found_relevant=0
            log "debounce: coalesced event for $wpath$fname"
            break
        fi
    done <<< "$output"
    return $found_relevant
}

watch() {
    log "starting inotifywait monitor"
    log "  watching RPZ dir: $RPZ_DIR"
    log "  watching forward-zones via dir: $FORWARD_ZONES_DIR (file: $FORWARD_ZONES_BASE)"
    log "  debounce: ${DEBOUNCE_SECONDS}s"
    log "  ignore pattern: $IGNORE_PATTERN"

    while true; do
        # Block until first event arrives
        local first_output
        first_output=$(inotifywait -q -r \
            -e close_write -e moved_to \
            --format '%w %f' \
            "$RPZ_DIR" "$FORWARD_ZONES_DIR" 2>/dev/null) || continue

        # Parse and check relevance of first event
        local first_wpath first_fname
        read -r first_wpath first_fname <<< "$first_output"

        local relevant=0
        if [ "$first_wpath" = "$FORWARD_ZONES_DIR/" ]; then
            [ "$first_fname" = "$FORWARD_ZONES_BASE" ] || relevant=1
        fi
        if [ "$relevant" -eq 0 ] && is_relevant "$first_fname"; then
            log "detected change: $first_wpath$first_fname"
        else
            # First event was noise; go back to waiting
            continue
        fi

        # Debounce: drain more events within the window
        while has_relevant_events; do
            : # keep draining
        done

        do_reload
    done
}

main() {
    log "starting recursor-reloader sidecar"
    check_tools
    wait_for_recursor
    log "entering watch loop"
    watch
}

if [ -z "${RELOADER_TEST_MODE:-}" ]; then
    main "$@"
fi
