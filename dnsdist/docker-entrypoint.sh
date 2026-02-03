#!/bin/sh
# dnsdist entrypoint that monitors dnstap-processor connectivity
# and restarts dnsdist if the connection is broken

DNSTAP_HOST="${DNSTAP_HOST:-172.30.0.20}"
DNSTAP_PORT="${DNSTAP_PORT:-6000}"
CHECK_INTERVAL="${DNSTAP_CHECK_INTERVAL:-10}"

# Function to check if dnstap-processor is accepting connections
check_dnstap() {
    nc -z -w2 "$DNSTAP_HOST" "$DNSTAP_PORT" 2>/dev/null
}

# Wait for dnstap-processor to be ready before starting dnsdist
echo "Waiting for dnstap-processor at $DNSTAP_HOST:$DNSTAP_PORT..."
while ! check_dnstap; do
    sleep 1
done
echo "dnstap-processor is ready"

# Start dnsdist in background
dnsdist --supervised -C /etc/dnsdist/dnsdist.conf &
DNSDIST_PID=$!

# Track the last known state of dnstap-processor
LAST_STATE="up"

# Monitor loop - if dnstap-processor goes down and comes back up, restart dnsdist
while kill -0 $DNSDIST_PID 2>/dev/null; do
    sleep "$CHECK_INTERVAL"
    
    if check_dnstap; then
        if [ "$LAST_STATE" = "down" ]; then
            echo "dnstap-processor is back up, restarting dnsdist to reconnect..."
            kill $DNSDIST_PID
            wait $DNSDIST_PID 2>/dev/null
            dnsdist --supervised -C /etc/dnsdist/dnsdist.conf &
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
