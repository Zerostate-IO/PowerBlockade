#!/bin/bash
# PowerBlockade Primary Node Deployment (Self-Contained)
# Usage: curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary-one-liner.sh | bash
# Or: ./deploy-primary-one-liner.sh [version]

set -e

VERSION="${1:-v0.5.5}"
REPO="zerostate-io"
DEPLOY_DIR="/opt/powerblockade"

echo "=== PowerBlockade Primary Node Deployment ==="
echo "Version: $VERSION"
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

# Download config files
mkdir -p recursor/rpz dnsdist grafana/provisioning/datasources grafana/provisioning/dashboards grafana/dashboards prometheus

curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/recursor/recursor.conf.template -o recursor/recursor.conf.template
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/recursor/rpz.lua -o recursor/rpz.lua
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/recursor/forward-zones.conf -o recursor/forward-zones.conf
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/dnsdist/dnsdist.conf.template -o dnsdist/dnsdist.conf.template
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/dnsdist/docker-entrypoint.sh -o dnsdist/docker-entrypoint.sh
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/prometheus/prometheus.yml -o prometheus/prometheus.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/grafana/provisioning/datasources/prometheus.yml -o grafana/provisioning/datasources/prometheus.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/grafana/provisioning/dashboards/dashboards.yml -o grafana/provisioning/dashboards/dashboards.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/grafana/dashboards/dns-overview.json -o grafana/dashboards/dns-overview.json

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

# Set version
export POWERBLOCKADE_VERSION="$VERSION"
export POWERBLOCKADE_REPO="$REPO"

# Pull images
echo ""
echo "Pulling Docker images..."
docker compose pull
echo "✓ Images pulled"

echo "Starting services (with primary profile)..."
docker compose --profile primary up -d
echo ""
echo "Starting services..."
docker compose up -d
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
echo "║          PowerBlockade Primary Node Deployed!                  ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║                                                                ║"
echo "║  Admin UI:  http://${SERVER_IP}:8080"
echo "║  Username:  admin                                              ║"
echo "║  Password:  $(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2 | head -c 30)..."
echo "║                                                                ║"
echo "║  DNS Port:  53 (UDP/TCP)                                       ║"
echo "║  Grafana:   http://${SERVER_IP}:8080/grafana"
echo "║                                                                ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║  SAVE THE PASSWORD ABOVE - it won't be shown again!           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Verification commands:"
echo "  docker compose ps              # Check service status"
echo "  dig @localhost google.com      # Test DNS"
echo "  curl http://localhost:8080/health  # Test admin UI"
echo ""
echo "Next steps:"
echo "  1. Login to Admin UI"
echo "  2. Go to Nodes → Add Node to register bowlister"
echo "  3. Note the API key for secondary deployment"