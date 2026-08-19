#!/bin/sh
# Materializes basic-auth credential files from the environment, then execs
# Prometheus.
#
# Static prometheus.yml cannot expand environment variables, so scrape jobs
# reference these files via `basic_auth.password_file`:
#   /dev/shm/secrets/recursor-web-password
#   /dev/shm/secrets/dnsdist-web-password
#
# /dev/shm is a memory-backed tmpfs inside the container: the secrets never
# touch the data volume or the host filesystem and vanish on restart. Files
# are written with umask 077 (owner read-only for the prometheus user).
#
# Both listeners accept any basic-auth username; only the password is
# checked (verified on powerdns/pdns-recursor-53:5.3.10 and
# powerdns/dnsdist-20:2.0.8). A missing/empty variable skips its file;
# Prometheus keeps running and scrape jobs referencing the missing file
# fail loudly instead of silently scraping with a wrong password.
set -e
umask 077

SECRETS_DIR=/dev/shm/secrets
mkdir -p "$SECRETS_DIR"

write_secret() {
  name="$1"
  value="${2:-}"
  if [ -n "$value" ]; then
    printf '%s' "$value" > "$SECRETS_DIR/$name"
    chmod 0400 "$SECRETS_DIR/$name"
  else
    echo "WARNING: $name not written (empty credential env); scrape jobs" >&2
    echo "referencing /dev/shm/secrets/$name will fail until the password" >&2
    echo "is set in .env and the stack is restarted." >&2
  fi
}

write_secret recursor-web-password "${RECURSOR_WEB_PASSWORD:-}"
write_secret dnsdist-web-password "${DNSDIST_WEB_PASSWORD:-}"

exec /bin/prometheus "$@"
