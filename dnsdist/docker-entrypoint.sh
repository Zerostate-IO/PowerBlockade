#!/bin/bash
set -e

# Raise the file-descriptor limit. dnsdist warns it needs >10000 FDs and the
# container default is 1024; without this, high query volumes can exhaust FDs.
ulimit -n "${DNSDIST_ULIMIT_NOFILE:-65536}" 2>/dev/null || true

# Network configuration (from environment or defaults)
RECURSOR_IP="${RECURSOR_IP:-172.30.0.10}"
DNSTAP_PROCESSOR_IP="${DNSTAP_PROCESSOR_IP:-172.30.0.20}"
DNSTAP_PORT="${DNSTAP_PORT:-6000}"
CHECK_INTERVAL="${DNSTAP_CHECK_INTERVAL:-10}"
DNSTAP_WAIT_TIMEOUT_SECONDS="${DNSTAP_WAIT_TIMEOUT_SECONDS:-60}"
RECURSOR_WAIT_TIMEOUT_SECONDS="${RECURSOR_WAIT_TIMEOUT_SECONDS:-30}"

# Generate dnsdist.conf from template with IP substitution
# Write to /tmp since /etc/dnsdist is read-only mounted
sed -e "s/\${RECURSOR_IP}/$RECURSOR_IP/g" \
    -e "s/\${DNSTAP_PROCESSOR_IP}/$DNSTAP_PROCESSOR_IP/g" \
    /etc/dnsdist/dnsdist.conf.template > /tmp/dnsdist.conf

echo "Generated dnsdist.conf with RECURSOR_IP=$RECURSOR_IP, DNSTAP_PROCESSOR_IP=$DNSTAP_PROCESSOR_IP"

check_dnstap() {
    timeout 2 bash -c "echo >/dev/tcp/$DNSTAP_PROCESSOR_IP/$DNSTAP_PORT" 2>/dev/null
}

check_recursor() {
    timeout 2 bash -c "echo >/dev/tcp/$RECURSOR_IP/5300" 2>/dev/null
}

check_dnsdist_local() {
    timeout 2 bash -c "echo >/dev/tcp/127.0.0.1/53" 2>/dev/null
}

wait_for_recursor() {
    # The DNS backend is the critical path: wait bounded, then FAIL CLOSED.
    # Starting dnsdist without a backend serves SERVFAIL to every client, and
    # Docker restart policies are not ordered at daemon boot, so this entrypoint
    # is the only guarantee that dnsdist never runs backend-less.
    WAIT_START=$(date +%s)
    TIMEOUT_SECS=$RECURSOR_WAIT_TIMEOUT_SECONDS
    echo "Waiting for recursor at $RECURSOR_IP:5300 (timeout: ${TIMEOUT_SECS}s)..."
    while true; do
        ELAPSED=$(($(date +%s) - WAIT_START))
        if [ $ELAPSED -ge $TIMEOUT_SECS ]; then
            echo "ERROR: recursor not ready after ${TIMEOUT_SECS}s; refusing to start dnsdist without a backend" >&2
            echo "Exiting so Docker restarts this container and retries" >&2
            exit 1
        fi
        if check_recursor; then
            echo "recursor is ready (${ELAPSED}s)"
            return 0
        fi
        sleep 1
    done
}

wait_for_dnstap() {
    # Logging is optional: DNS should work even when the pipeline is down.
    WAIT_START=$(date +%s)
    TIMEOUT_SECS=$DNSTAP_WAIT_TIMEOUT_SECONDS
    echo "Waiting for dnstap-processor at $DNSTAP_PROCESSOR_IP:$DNSTAP_PORT (timeout: ${TIMEOUT_SECS}s)..."
    while true; do
        ELAPSED=$(($(date +%s) - WAIT_START))
        if [ $ELAPSED -ge $TIMEOUT_SECS ]; then
            echo "WARNING: dnstap-processor not ready after ${TIMEOUT_SECS}s, starting dnsdist without dnstap logging"
            echo "DNS queries will be served but not logged until dnstap-processor becomes available"
            return 1
        fi
        if check_dnstap; then
            echo "dnstap-processor is ready (${ELAPSED}s)"
            return 0
        fi
        sleep 1
    done
}

# Recursor readiness first (fail closed), then optional dnstap logging.
wait_for_recursor
wait_for_dnstap || true

# Start dnsdist in background
dnsdist --supervised -C /tmp/dnsdist.conf &
DNSDIST_PID=$!

DNSDIST_READY=false
for _ in $(seq 1 10); do
    if ! kill -0 $DNSDIST_PID 2>/dev/null; then
        break
    fi

    if check_dnsdist_local; then
        DNSDIST_READY=true
        echo "dnsdist is listening on 127.0.0.1:53"
        break
    fi

    sleep 1
done

if [ "$DNSDIST_READY" != "true" ]; then
    echo "ERROR: dnsdist did not become reachable on 127.0.0.1:53" >&2
    if kill -0 $DNSDIST_PID 2>/dev/null; then
        kill $DNSDIST_PID 2>/dev/null || true
        wait $DNSDIST_PID 2>/dev/null || true
    fi
    exit 1
fi

# NOTE: deliberately no dnstap-monitor restart loop here. The framestream
# logger reconnects automatically (reopenInterval in dnsdist.conf.template),
# and restarting dnsdist when dnstap-processor returns only creates avoidable
# DNS outages during boot (observed on celsate, 2026-08-17: 4+ restart cycles
# in one boot). Log-only monitoring keeps startup stable.
echo "dnsdist is up; monitoring only (no restart-on-dnstap-recovery)"

# Supervise dnsdist: if it exits, exit with its status so Docker restarts us.
wait $DNSDIST_PID
