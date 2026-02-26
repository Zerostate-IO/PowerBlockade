#!/bin/bash
# PowerBlockade Secondary Node Deployment (Self-Contained)
# Usage: curl -fsSL ... | bash -s -- PRIMARY_URL API_KEY NODE_NAME
# Example: curl -fsSL ... | bash -s -- http://192.168.1.10:8080 abc123... bowlister

set -e

VERSION="${VERSION:-v0.5.5}"
PRIMARY_URL="${1:-}"
PRIMARY_API_KEY="${2:-}"
NODE_NAME="${3:-$(hostname)}"
REPO="zerostate-io"
DEPLOY_DIR="/opt/powerblockade"

# Validate required params
if [[ -z "$PRIMARY_URL" ]]; then
    echo "Error: PRIMARY_URL is required"
    echo "Usage: $0 [primary_url] [api_key] [node_name]"
    echo "Example: $0 http://192.168.1.10:8080 abc123def456 bowlister"
    exit 1
fi

if [[ -z "$PRIMARY_API_KEY" ]]; then
    echo "Error: PRIMARY_API_KEY is required"
    echo "Get this from the primary node's Admin UI -> Nodes page"
    echo "Usage: $0 [primary_url] [api_key] [node_name]"
    exit 1
fi

echo "=== PowerBlockade Secondary Node Deployment ==="
echo "Version: $VERSION"
echo "Node name: $NODE_NAME"
echo "Primary URL: $PRIMARY_URL"
echo "Deploy directory: $DEPLOY_DIR"
echo ""

# Create deployment directory
if [[ ! -d "$DEPLOY_DIR" ]]; then
    echo "Creating deployment directory..."
    sudo mkdir -p "$DEPLOY_DIR"
    sudo chown $USER:$USER "$DEPLOY_DIR"
fi

cd "$DEPLOY_DIR"

# Download required files
echo "Downloading configuration files..."
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/docker-compose.ghcr.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/.env.example -o .env

# Download config files (minimal for secondary)
mkdir -p recursor/rpz dnsdist
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/recursor/recursor.conf.template -o recursor/recursor.conf.template
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/recursor/rpz.lua -o recursor/rpz.lua
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/recursor/forward-zones.conf -o recursor/forward-zones.conf
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/dnsdist/dnsdist.conf.template -o dnsdist/dnsdist.conf.template
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/dnsdist/docker-entrypoint.sh -o dnsdist/docker-entrypoint.sh

echo "✓ Configuration files downloaded"

# Generate secure passwords
echo ""
echo "Generating secure passwords..."
generate_password() { openssl rand -base64 24 | tr -d '\n' | tr '+/' '-_'; }

sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$(generate_password)/" .env
sed -i "s/^ADMIN_SECRET_KEY=.*/ADMIN_SECRET_KEY=$(generate_password)$(generate_password)/" .env
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(generate_password)/" .env
sed -i "s/^RECURSOR_API_KEY=.*/RECURSOR_API_KEY=$(generate_password)/" .env
sed -i "s/^PRIMARY_API_KEY=.*/PRIMARY_API_KEY=$(generate_password)/" .env
sed -i "s/^GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$(generate_password)/" .env

# Fix DATABASE_URL
PGPASS=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2)
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://powerblockade:${PGPASS}@postgres:5432/powerblockade|" .env

echo "✓ Passwords generated"

# Configure secondary node settings
echo ""
echo "Configuring secondary node settings..."
sed -i "s/^NODE_NAME=.*/NODE_NAME=$NODE_NAME/" .env
sed -i "s|^PRIMARY_URL=.*|PRIMARY_URL=$PRIMARY_URL|" .env
sed -i "s/^PRIMARY_API_KEY=.*/PRIMARY_API_KEY=$PRIMARY_API_KEY/" .env
sed -i "s/^LOCAL_NODE_API_KEY=.*/LOCAL_NODE_API_KEY=$(generate_password)/" .env

echo "✓ Secondary node configured"

# Set version
export POWERBLOCKADE_VERSION="$VERSION"
export POWERBLOCKADE_REPO="$REPO"

# Pull images
echo ""
echo "Pulling Docker images..."
docker compose pull
echo "✓ Images pulled"

# Start services with sync-agent profile
echo ""
echo "Starting services (with sync-agent profile)..."
docker compose --profile sync-agent up -d
echo "✓ Services started"

# Wait for services
echo ""
echo "Waiting for services to be healthy..."
sleep 15

# Get server IP
SERVER_IP=$(hostname -I | awk '{print $1}')

# Show results
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║          PowerBlockade Secondary Node Deployed!                ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║                                                                ║"
echo "║  Node Name: $NODE_NAME"
echo "║  Primary:   $PRIMARY_URL"
echo "║  DNS Port:  53 (UDP/TCP)                                       ║"
echo "║                                                                ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║  This node will sync config from the primary                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Verification commands:"
echo "  docker compose ps              # Check service status"
echo "  docker compose logs sync-agent # Check sync status"
echo "  dig @localhost google.com      # Test DNS"
echo ""
echo "On the primary (${PRIMARY_URL}):"
echo "  Go to Admin UI → Nodes → '$NODE_NAME' should show 'Online'"