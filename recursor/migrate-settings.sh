#!/usr/bin/env sh
set -eu

INPUT_PATH="${1:-}"
OUTPUT_PATH="${2:-${INPUT_PATH}}"

if [ -z "$INPUT_PATH" ]; then
  echo "Usage: $0 <input-conf> [output-conf]" >&2
  exit 1
fi

if [ ! -f "$INPUT_PATH" ]; then
  echo "Input file not found: $INPUT_PATH" >&2
  exit 1
fi

TMP_FILE="$(mktemp "${TMPDIR:-/tmp}/recursor-migrate.XXXXXX")"

awk '
BEGIN {
  map["recordcache-max-entries"] = "max-cache-entries"
  map["cache-ttl"] = "packetcache-ttl"
  map["negquery-cache-ttl"] = "packetcache-negative-ttl"
  map["negcache-ttl"] = "packetcache-negative-ttl"
  map["reuse-port"] = "reuseport"
}

function ltrim(s) { sub(/^[ \t]+/, "", s); return s }
function rtrim(s) { sub(/[ \t]+$/, "", s); return s }
function trim(s) { return rtrim(ltrim(s)) }

{
  raw = $0

  if (raw ~ /^[[:space:]]*#/ || raw ~ /^[[:space:]]*$/ || index(raw, "=") == 0) {
    print raw
    next
  }

  eq = index(raw, "=")
  key = trim(substr(raw, 1, eq - 1))
  value = substr(raw, eq + 1)

  newkey = key
  if (key in map) {
    newkey = map[key]
    migrated++
  }

  if (newkey in seen) {
    deduped++
    next
  }

  seen[newkey] = 1
  print newkey "=" value
}

END {
  printf("migrate-recursor-settings: migrated=%d deduped=%d\n", migrated, deduped) > "/dev/stderr"
}
' "$INPUT_PATH" > "$TMP_FILE"

if [ "$OUTPUT_PATH" = "$INPUT_PATH" ]; then
  cp "$INPUT_PATH" "$INPUT_PATH.bak.pre-migration"
fi

mv "$TMP_FILE" "$OUTPUT_PATH"
