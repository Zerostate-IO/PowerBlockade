#!/bin/bash
set -e

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

# Wait for dnstap-processor with bounded timeout
# DNS should work even when logging pipeline is unavailable
WAIT_START=$(date +%s)
TIMEOUT_SECS=$DNSTAP_WAIT_TIMEOUT_SECONDS
echo "Waiting for dnstap-processor at $DNSTAP_PROCESSOR_IP:$DNSTAP_PORT (timeout: ${TIMEOUT_SECS}s)..."

DNSTAP_READY=false
while true; do
    ELAPSED=$(($(date +%s) - WAIT_START))
    if [ $ELAPSED -ge $TIMEOUT_SECS ]; then
        echo "WARNING: dnstap-processor not ready after ${TIMEOUT_SECS}s, starting dnsdist without dnstap logging"
        echo "DNS queries will be served but not logged until dnstap-processor becomes available"
        break
    fi
    
    if check_dnstap; then
        echo "dnstap-processor is ready (${ELAPSED}s)"
        DNSTAP_READY=true
        break
    fi
    
    sleep 1
done


RECURSOR_WAIT_START=$(date +%s)
echo "Waiting for recursor at $RECURSOR_IP:5300 (timeout: ${RECURSOR_WAIT_TIMEOUT_SECONDS}s)..."

while true; do
    ELAPSED=$(($(date +%s) - RECURSOR_WAIT_START))
    if [ $ELAPSED -ge $RECURSOR_WAIT_TIMEOUT_SECONDS ]; then
        echo "WARNING: recursor not ready after ${RECURSOR_WAIT_TIMEOUT_SECONDS}s, starting dnsdist anyway"
        break
    fi

    if check_recursor; then
        echo "recursor is ready (${ELAPSED}s)"
        break
    fi

    sleep 1
done


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

# Track the last known state of dnstap-processor
if [ "$DNSTAP_READY" = "true" ]; then
    LAST_STATE="up"
else
    LAST_STATE="down"
fi

# Monitor loop - if dnstap-processor goes down and comes back up, restart dnsdist
while kill -0 $DNSDIST_PID 2>/dev/null; do
    sleep "$CHECK_INTERVAL"
    
    if check_dnstap; then
        if [ "$LAST_STATE" = "down" ]; then
            echo "dnstap-processor is back up, restarting dnsdist to reconnect..."
            kill $DNSDIST_PID
            wait $DNSDIST_PID 2>/dev/null
            dnsdist --supervised -C /tmp/dnsdist.conf &
            DNSDIST_PID=$!
        fi
        LAST_STATE="up"
    else
        if [ "$LAST_STATE" = "up" ]; then
            echo "dnstap-processor connection lost, waiting for it to come back..."
        fi
        LAST_STATE="down"
    fi
done

# If dnsdist exits, exit with its status
wait $DNSDIST_PID
