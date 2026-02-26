#!/bin/bash
set -e

# Network configuration (from environment or defaults)
RECURSOR_IP="${RECURSOR_IP:-172.30.0.10}"
DNSTAP_PROCESSOR_IP="${DNSTAP_PROCESSOR_IP:-172.30.0.20}"
DNSTAP_PORT="${DNSTAP_PORT:-6000}"
CHECK_INTERVAL="${DNSTAP_CHECK_INTERVAL:-10}"

# Generate dnsdist.conf from template with IP substitution
# Write to /tmp since /etc/dnsdist is read-only mounted
sed -e "s/\${RECURSOR_IP}/$RECURSOR_IP/g" \
    -e "s/\${DNSTAP_PROCESSOR_IP}/$DNSTAP_PROCESSOR_IP/g" \
    /etc/dnsdist/dnsdist.conf.template > /tmp/dnsdist.conf

echo "Generated dnsdist.conf with RECURSOR_IP=$RECURSOR_IP, DNSTAP_PROCESSOR_IP=$DNSTAP_PROCESSOR_IP"

check_dnstap() {
    timeout 2 bash -c "echo >/dev/tcp/$DNSTAP_PROCESSOR_IP/$DNSTAP_PORT" 2>/dev/null
}

# Wait for dnstap-processor to be ready before starting dnsdist
echo "Waiting for dnstap-processor at $DNSTAP_PROCESSOR_IP:$DNSTAP_PORT..."
while ! check_dnstap; do
    sleep 1
done
echo "dnstap-processor is ready"

# Start dnsdist in background
dnsdist --supervised -C /tmp/dnsdist.conf &
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