#!/bin/bash
# PowerBlockade Upgrade Script
# Usage: ./upgrade.sh [version]
# Example: ./upgrade.sh v0.6.1

set -e

NEW_VERSION="${1:-}"
DEPLOY_DIR="/opt/powerblockade"

if [[ -z "$NEW_VERSION" ]]; then
    echo "Usage: $0 [version]"
    echo "Example: $0 v0.6.1"
    exit 1
fi

cd "$DEPLOY_DIR"

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
CURRENT_VERSION=$(grep "^POWERBLOCKADE_VERSION=" .env 2>/dev/null | cut -d= -f2 || echo "latest")
echo "Current version: $CURRENT_VERSION"
echo ""

# Backup database
echo "Backing up database..."
mkdir -p backups
docker compose exec -T postgres pg_dump -U powerblockade powerblockade > "backups/backup_$(date +%Y%m%d_%H%M%S).sql"
echo "✓ Database backed up"

# Pull new images
echo ""
echo "Pulling new images (version: $NEW_VERSION)..."
export POWERBLOCKADE_VERSION="$NEW_VERSION"
docker compose pull
echo "✓ Images pulled"

# Stop services
echo ""
echo "Stopping services..."
docker compose down
echo "✓ Services stopped"

# Start with new images
echo ""
echo "Starting services with version $NEW_VERSION..."
if [ "$IS_SECONDARY" = "true" ]; then
    docker compose --profile sync-agent up -d
else
    docker compose up -d
fi
echo "✓ Services started"

# Wait for health
echo ""
echo "Waiting for services to be healthy..."
sleep 10

# Verify
echo ""
echo "Verifying deployment..."
if docker compose ps | grep -q "Up"; then
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