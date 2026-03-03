#!/bin/bash
# PowerBlockade Deployment Script for Primary Node
# Usage: ./deploy-primary.sh [version]

set -e

VERSION="${1:-latest}"
REPO="${POWERBLOCKADE_REPO:-zerostate-io}"
DEPLOY_DIR="/opt/powerblockade"

echo "=== PowerBlockade Primary Node Deployment ==="
echo "Version: $VERSION"
echo "Repository: $REPO"
echo "Deploy directory: $DEPLOY_DIR"
echo ""

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
mkdir -p recursor/rpz dnsdist grafana/provisioning/datasources grafana/provisioning/dashboards grafana/dashboards prometheus

for file in \
    "recursor/recursor.conf.template:recursor/recursor.conf.template" \
    "recursor/rpz.lua:recursor/rpz.lua" \
    "recursor/forward-zones.conf:recursor/forward-zones.conf" \
    "dnsdist/dnsdist.conf.template:dnsdist/dnsdist.conf.template" \
    "dnsdist/docker-entrypoint.sh:dnsdist/docker-entrypoint.sh" \
    "prometheus/prometheus.yml:prometheus/prometheus.yml" \
    "grafana/provisioning/datasources/prometheus.yml:grafana/provisioning/datasources/prometheus.yml" \
    "grafana/provisioning/dashboards/dashboards.yml:grafana/provisioning/dashboards/dashboards.yml" \
    "grafana/dashboards/dns-overview.json:grafana/dashboards/dns-overview.json"
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
    
    # Use init-env.sh to bootstrap environment (non-interactive, auto-generates secrets)
    ./scripts/init-env.sh --non-interactive
    
    echo ""
fi

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

echo "Starting services..."
docker compose up -d

echo ""
echo "=== Deployment Complete ==="
echo "Admin UI: http://$(hostname -I | awk '{print $1}'):8080"
echo "Username: admin"
echo "Password: (see .env file)"
echo ""
echo "Useful commands:"
echo "  docker compose ps          - Check service status"
echo "  docker compose logs -f     - Follow logs"
echo "  docker compose down        - Stop services"
echo ""
echo "To upgrade:"
echo "  POWERBLOCKADE_VERSION=v0.7.0 docker compose pull"
echo "  POWERBLOCKADE_VERSION=v0.7.0 docker compose up -d"
