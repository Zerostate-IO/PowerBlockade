#!/usr/bin/env sh
set -eu

TEMPLATE=/etc/pdns-recursor/recursor.conf.template
OUT=/etc/pdns-recursor/recursor.conf

if [ -f "$TEMPLATE" ]; then
  # Template supports a single ${RECURSOR_API_KEY} substitution.
  # Avoid extra deps (envsubst) to keep image minimal.
  if [ -z "${RECURSOR_API_KEY:-}" ]; then
    echo "RECURSOR_API_KEY is required" >&2
    exit 1
  fi
  sed "s|\${RECURSOR_API_KEY}|${RECURSOR_API_KEY}|g" "$TEMPLATE" > "$OUT"
fi

# Ensure runtime dirs exist
mkdir -p /var/run/dnstap
mkdir -p /var/run/pdns-recursor
chmod 0777 /var/run/dnstap || true
chmod 0777 /var/run/pdns-recursor || true

# Ensure RPZ zone files exist (empty-but-valid zones)
# The RPZ files are bind-mounted from ./recursor/rpz
mkdir -p /etc/pdns-recursor/rpz

if [ ! -f /etc/pdns-recursor/rpz/blocklist-combined.rpz ]; then
  cat > /etc/pdns-recursor/rpz/blocklist-combined.rpz <<'EOF'
$TTL 60
@ IN SOA localhost. hostmaster.localhost. 1 1h 15m 30d 2h
  IN NS localhost.
EOF
fi

if [ ! -f /etc/pdns-recursor/rpz/whitelist.rpz ]; then
  cat > /etc/pdns-recursor/rpz/whitelist.rpz <<'EOF'
$TTL 60
@ IN SOA localhost. hostmaster.localhost. 1 1h 15m 30d 2h
  IN NS localhost.
EOF
fi

exec "$@"
