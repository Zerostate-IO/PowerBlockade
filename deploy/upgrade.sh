#!/bin/bash
# PowerBlockade Upgrade Script
# Usage: ./upgrade.sh [version]

set -e

NEW_VERSION="${1:-}"
DEFAULT_DEPLOY_DIR="/opt/powerblockade"
ALT_DEPLOY_DIR="/opt/PowerBlockade"

if [[ -d "$DEFAULT_DEPLOY_DIR" ]]; then
    DEPLOY_DIR="$DEFAULT_DEPLOY_DIR"
elif [[ -d "$ALT_DEPLOY_DIR" ]]; then
    DEPLOY_DIR="$ALT_DEPLOY_DIR"
else
    echo "Could not find deployment directory at $DEFAULT_DEPLOY_DIR or $ALT_DEPLOY_DIR"
    exit 1
fi

if [[ -z "$NEW_VERSION" ]]; then
    echo "Usage: $0 [version]"
    echo "Example: $0 v0.7.0"
    exit 1
fi

cd "$DEPLOY_DIR"

COMPOSE_FILE="$DEPLOY_DIR/docker-compose.ghcr.yml"
if [[ ! -f "$COMPOSE_FILE" ]]; then
    COMPOSE_FILE="$DEPLOY_DIR/compose.yaml"
fi
COMPOSE_CMD=(docker compose -f "$COMPOSE_FILE")

CURRENT_VERSION="$(grep '^POWERBLOCKADE_VERSION=' .env 2>/dev/null | cut -d= -f2 || true)"
CURRENT_VERSION="${CURRENT_VERSION:-latest}"

# Detect if this is a secondary node
IS_SECONDARY="false"
if grep -q "^NODE_NAME=primary$" .env 2>/dev/null; then
    IS_SECONDARY="false"
elif grep -q "^PRIMARY_URL=" .env 2>/dev/null; then
    IS_SECONDARY="true"
fi

echo "=== PowerBlockade Upgrade ==="
echo "Current directory: $DEPLOY_DIR"
echo "Target version: $NEW_VERSION"
echo "Node type: $(if [ "$IS_SECONDARY" = "true" ]; then echo "secondary"; else echo "primary"; fi)"
echo ""

# Check current version
echo "Current version: $CURRENT_VERSION"
echo "Compose file: $COMPOSE_FILE"
echo ""

# Check GHCR authentication
check_ghcr_auth() {
    if docker pull ghcr.io/zerostate-io/powerblockade-admin-ui:latest 2>&1 | grep -q "403 Forbidden"; then
        echo ""
        echo "⚠️  GHCR Authentication Required"
        echo "The Docker images are private. You must login to GHCR first:"
        echo ""
        echo "  1. Create a GitHub token with 'read:packages' scope:"
        echo "     https://github.com/settings/tokens"
        echo ""
        echo "  2. Login to GHCR:"
        echo "     echo \"YOUR_TOKEN\" | docker login ghcr.io -u YOUR_USERNAME --password-stdin"
        echo ""
        echo "  3. Re-run this script."
        echo ""
        echo "Alternative: Make packages public at:"
        echo "  https://github.com/orgs/Zerostate-IO/packages"
        echo ""
        exit 1
    fi
}

migrate_recursor_template() {
    local template_path="recursor/recursor.conf.template"

if [[ ! -f "$template_path" ]]; then
        echo "⚠ recursor template not found, skipping migration"
        return 0
    fi

    cp "$template_path" "${template_path}.bak.pre-migration"

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
  newkey = (key in map) ? map[key] : key

  if (newkey in seen) {
    next
  }

  seen[newkey] = 1
  print newkey "=" value
}
' "$template_path" > "${template_path}.migrated"

    mv "${template_path}.migrated" "$template_path"
    echo "✓ Recursor settings migration complete"
}

echo "Checking GHCR access..."
check_ghcr_auth

echo "Running recursor settings migration..."
migrate_recursor_template

# Backup database
if [ "$IS_SECONDARY" = "true" ]; then
    echo "Skipping database backup on secondary node"
else
    echo "Backing up database..."
    mkdir -p backups
    "${COMPOSE_CMD[@]}" exec -T postgres pg_dump -U powerblockade powerblockade > "backups/backup_$(date +%Y%m%d_%H%M%S).sql"
    echo "✓ Database backed up"
fi

# Pull new images
echo ""
echo "Pulling new images (version: $NEW_VERSION)..."
export POWERBLOCKADE_VERSION="$NEW_VERSION"
"${COMPOSE_CMD[@]}" pull
echo "✓ Images pulled"

# Stop services
echo ""
echo "Stopping services..."
"${COMPOSE_CMD[@]}" down
echo "✓ Services stopped"

echo ""
echo "Starting services with version $NEW_VERSION..."
if [ "$IS_SECONDARY" = "true" ]; then
    "${COMPOSE_CMD[@]}" --profile secondary up -d
else
    "${COMPOSE_CMD[@]}" up -d
fi
echo "✓ Services started"

# Wait for health
echo ""
echo "Waiting for services to be healthy..."
sleep 10

# Verify
echo ""
echo "Verifying deployment..."
if "${COMPOSE_CMD[@]}" ps | grep -q "Up"; then
    echo "✓ All services running"
else
    echo "⚠ Some services may not be running - check 'docker compose ps'"
fi

# Test DNS
if dig @localhost +short google.com > /dev/null 2>&1; then
    echo "✓ DNS resolution working"
else
    echo "⚠ DNS may not be working - check 'docker compose logs dnsdist'"
fi

# Update .env with new version
sed -i "s/^POWERBLOCKADE_VERSION=.*/POWERBLOCKADE_VERSION=$NEW_VERSION/" .env 2>/dev/null || \
    echo "POWERBLOCKADE_VERSION=$NEW_VERSION" >> .env

echo ""
echo "=== Upgrade Complete ==="
echo "Version: $NEW_VERSION"
echo ""
echo "Rollback command (if needed):"
echo "  POWERBLOCKADE_VERSION=$CURRENT_VERSION docker compose pull"
echo "  POWERBLOCKADE_VERSION=$CURRENT_VERSION docker compose up -d"
