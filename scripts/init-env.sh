#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
ENV_EXAMPLE="$ROOT_DIR/.env.example"

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require openssl

rand_b64() {
  # URL-ish safe base64
  openssl rand -base64 "$1" | tr -d '\n' | tr '+/' '-_' | tr -d '='
}

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$ENV_EXAMPLE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
  else
    touch "$ENV_FILE"
  fi
fi

set_kv_if_missing() {
  local key="$1"
  local value="$2"
  if ! grep -qE "^${key}=" "$ENV_FILE"; then
    echo "${key}=${value}" >> "$ENV_FILE"
    return
  fi
  # present but empty -> fill
  if grep -qE "^${key}=$" "$ENV_FILE"; then
    perl -0777 -i -pe "s/^${key}=\$/${key}=${value}/m" "$ENV_FILE"
  fi
}

# Core secrets
set_kv_if_missing "ADMIN_SECRET_KEY" "$(rand_b64 48)"
set_kv_if_missing "ADMIN_PASSWORD" "$(rand_b64 18)"
set_kv_if_missing "POSTGRES_PASSWORD" "$(rand_b64 24)"
set_kv_if_missing "RECURSOR_API_KEY" "$(rand_b64 24)"

# Node auth for the primary's local dnstap-processor -> admin-ui ingest.
set_kv_if_missing "PRIMARY_API_KEY" "$(rand_b64 24)"

echo "Wrote/updated: $ENV_FILE"
echo "- ADMIN_PASSWORD was generated if missing"
