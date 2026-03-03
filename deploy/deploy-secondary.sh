#!/bin/bash
# PowerBlockade Deployment Script for Secondary Node
# Usage: ./deploy-secondary.sh [version] [primary_url] [api_key] [node_name]

set -e

VERSION="${1:-latest}"
PRIMARY_URL="${2:-}"
PRIMARY_API_KEY="${3:-}"
NODE_NAME="${4:-$(hostname)}"
REPO="${POWERBLOCKADE_REPO:-zerostate-io}"
DEPLOY_DIR="/opt/powerblockade"

echo "=== PowerBlockade Secondary Node Deployment ==="
echo "Version: $VERSION"
echo "Repository: $REPO"
echo "Node name: $NODE_NAME"
echo "Primary URL: $PRIMARY_URL"
echo "Deploy directory: $DEPLOY_DIR"
echo ""

# Validate required params
if [[ -z "$PRIMARY_URL" ]]; then
    echo "Error: PRIMARY_URL is required"
    echo "Usage: $0 [version] [primary_url] [api_key] [node_name]"
    exit 1
fi

if [[ -z "$PRIMARY_API_KEY" ]]; then
    echo "Error: PRIMARY_API_KEY is required"
    echo "Get this from the primary node's Admin UI -> Nodes page"
    echo "Usage: $0 [version] [primary_url] [api_key] [node_name]"
    exit 1
fi

# Create deployment directory
if [[ ! -d "$DEPLOY_DIR" ]]; then
    echo "Creating deployment directory..."
    sudo mkdir -p "$DEPLOY_DIR"
    sudo chown $USER:$USER "$DEPLOY_DIR"
fi

cd "$DEPLOY_DIR"

# Download required files if not present
if [[ ! -f "docker-compose.yml" ]]; then
    echo "Downloading docker-compose.ghcr.yml..."
    curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/docker-compose.ghcr.yml -o docker-compose.yml
fi

# Download config files
echo "Ensuring config files exist..."
mkdir -p recursor/rpz dnsdist

for file in \
    "recursor/recursor.conf.template:recursor/recursor.conf.template" \
    "recursor/rpz.lua:recursor/rpz.lua" \
    "recursor/forward-zones.conf:recursor/forward-zones.conf" \
    "dnsdist/dnsdist.conf.template:dnsdist/dnsdist.conf.template" \
    "dnsdist/docker-entrypoint.sh:dnsdist/docker-entrypoint.sh"
do
    remote="${file%%:*}"
    local="${file#*:}"
    if [[ ! -f "$local" ]]; then
        echo "  Downloading $local..."
        curl -fsSL "https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/$remote" -o "$local"
    fi
done

# Generate .env if not present
if [[ ! -f ".env" ]]; then
    echo "Generating .env file..."
    
    # Download init-env.sh if not present
    if [[ ! -f "scripts/init-env.sh" ]]; then
        mkdir -p scripts
        curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/scripts/init-env.sh -o scripts/init-env.sh
        chmod +x scripts/init-env.sh
    fi
    
    # Use init-env.sh to bootstrap environment (non-interactive with node name)
    ./scripts/init-env.sh --non-interactive --node-name "$NODE_NAME"
    
    echo ""
fi

# Set secondary node configuration
# Note: NODE_NAME is already set via init-env.sh --node-name
# These are secondary-specific settings not handled by init-env.sh
sed -i "s|^PRIMARY_URL=.*|PRIMARY_URL=$PRIMARY_URL|" .env
sed -i "s/^PRIMARY_API_KEY=.*/PRIMARY_API_KEY=$PRIMARY_API_KEY/" .env
sed -i "s/^LOCAL_NODE_API_KEY=.*/LOCAL_NODE_API_KEY=$(openssl rand -base64 24 | tr -d '\n' | tr '+/' '-_')/" .env

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

echo "Checking GHCR access..."
check_ghcr_auth

# Set version
echo "Pulling images..."
docker compose pull

echo "Starting services (with secondary profile)..."
docker compose --profile secondary up -d

echo ""
echo "=== Secondary Node Deployment Complete ==="
echo "Node name: $NODE_NAME"
echo "Primary: $PRIMARY_URL"
echo ""
echo "Check sync status:"
echo "  docker compose logs sync-agent"
echo ""
echo "Verify on primary:"
echo "  Go to Admin UI -> Nodes -> $NODE_NAME should show 'Online'"
echo ""
echo "To upgrade:"
echo "  POWERBLOCKADE_VERSION=v0.7.0 docker compose pull"
echo "  POWERBLOCKADE_VERSION=v0.7.0 docker compose --profile secondary up -d"
