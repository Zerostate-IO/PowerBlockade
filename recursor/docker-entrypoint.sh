#!/usr/bin/env sh
set -eu

TEMPLATE=/etc/pdns-recursor/recursor.conf.template
OUT=/etc/pdns-recursor/recursor.conf

if [ -f "$TEMPLATE" ]; then
  # Template supports ${RECURSOR_API_KEY} and ${RECURSOR_WEB_PASSWORD}
  # substitutions. Avoid extra deps (envsubst) to keep image minimal.
  if [ -z "${RECURSOR_API_KEY:-}" ]; then
    echo "RECURSOR_API_KEY is required" >&2
    exit 1
  fi
  # Dedicated webserver password (never the API key). /metrics and the API
  # both live on the webserver, and an EMPTY webserver-password leaves the
  # whole webserver unauthenticated (verified on 5.3.10). So never start
  # passwordless: an unset or invalid RECURSOR_WEB_PASSWORD generates a
  # random per-start password with a prominent warning instead. Scrapers
  # (prometheus, sync-agent, admin-ui) get 401s until a real value is set.
  gen_web_password() {
    LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32
  }
  warn_random_password() {
    echo "**************************************************************************" >&2
    echo "WARNING: $1" >&2
    echo "Generated a RANDOM webserver password for this container start." >&2
    echo "The webserver stays authenticated, but /metrics scraping (prometheus," >&2
    echo "sync-agent, admin-ui local metrics) will fail with 401 until you set" >&2
    echo "RECURSOR_WEB_PASSWORD in .env (chars: A-Za-z0-9 . _ ~ + = @ -) and" >&2
    echo "restart the stack." >&2
    echo "**************************************************************************" >&2
  }
  if [ -z "${RECURSOR_WEB_PASSWORD:-}" ]; then
    RECURSOR_WEB_PASSWORD=$(gen_web_password)
    warn_random_password "RECURSOR_WEB_PASSWORD is not set."
  elif ! printf '%s' "$RECURSOR_WEB_PASSWORD" | LC_ALL=C grep -Eq '^[A-Za-z0-9._~+=@-]+$'; then
    # Reject characters that could break the ini/HTTP credentials (newline,
    # quotes, whitespace, sed metacharacters) rather than inject them.
    RECURSOR_WEB_PASSWORD=$(gen_web_password)
    warn_random_password "RECURSOR_WEB_PASSWORD contains characters outside [A-Za-z0-9._~+=@-]."
  fi
  # Escape sed replacement metacharacters so generated secrets (base64
  # values can contain / + =, other generators may emit \ | &) cannot
  # break the substitution or inject config lines.
  api_key_esc=$(printf '%s' "$RECURSOR_API_KEY" | sed -e 's/[\\|&]/\\&/g')
  web_pass_esc=$(printf '%s' "$RECURSOR_WEB_PASSWORD" | sed -e 's/[\\|&]/\\&/g')
  sed -e "s|\${RECURSOR_API_KEY}|${api_key_esc}|g" \
      -e "s|\${RECURSOR_WEB_PASSWORD}|${web_pass_esc}|g" \
      "$TEMPLATE" > "$OUT"

  if command -v migrate-recursor-settings >/dev/null 2>&1; then
    migrate-recursor-settings "$OUT" "$OUT" || {
      echo "failed to migrate recursor settings" >&2
      exit 1
    }
  fi
fi

# Ensure runtime dirs exist
mkdir -p /var/run/dnstap
mkdir -p /var/run/pdns-recursor
chmod 0777 /var/run/dnstap || true
chmod 0777 /var/run/pdns-recursor || true

# Remove stale control-socket/pid files left by an unclean shutdown. A leftover
# socket file makes pdns_recursor fail to bind its control socket, which breaks
# the rec_control healthcheck and with it the whole stack's readiness gating.
# The reloader sidecar only connects to this socket; it never creates files.
rm -f /var/run/pdns-recursor/pdns_recursor.controlsocket \
      /var/run/pdns-recursor/pdns_recursor.pid 2>/dev/null || true

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
