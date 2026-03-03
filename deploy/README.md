# PowerBlockade Deployment Guide

This directory contains scripts for deploying PowerBlockade to production servers using pre-built Docker images from GitHub Container Registry (GHCR).

## Quick Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `deploy-primary.sh` | Deploy primary node | `./deploy-primary.sh [version]` |
| `deploy-secondary.sh` | Deploy secondary node | `./deploy-secondary.sh [version] [primary_url] [api_key] [node_name]` |
| `upgrade.sh` | Upgrade existing deployment | `./upgrade.sh [version]` |

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│    CELSATE      │         │   BOWLISTER      │
│   (Primary)     │◄───────►│   (Secondary)    │
│                 │  sync   │                  │
│  - Admin UI     │         │  - DNS only      │
│  - Database     │         │  - sync-agent    │
│  - Grafana      │         │                  │
│  - DNS (dnsdist)│         │  - DNS (dnsdist) │
└─────────────────┘         └─────────────────┘
```

## Deploy Primary Node (celsate)

1. Copy the deploy directory to celsate:
   ```bash
   scp -r deploy/ user@celsate:/opt/powerblockade-deploy/
   ```

2. SSH to celsate and run:
   ```bash
   cd /opt/powerblockade-deploy
   chmod +x deploy-primary.sh
   ./deploy-primary.sh latest
   ```

3. Note the generated admin password from the output.

4. Access the Admin UI at `http://celsate:8080`

5. Go to **Nodes** → **Add Node** to register bowlister.

## Deploy Secondary Node (bowlister)

1. On celsate, generate a node package:
   - Go to **Nodes** → **Add Node**
   - Enter name: `bowlister`
   - Click **Generate Deployment Package**
   - Note the API key

2. Copy the deploy directory to bowlister:
   ```bash
   scp -r deploy/ user@bowlister:/opt/powerblockade-deploy/
   ```

3. SSH to bowlister and run:
   ```bash
   cd /opt/powerblockade-deploy
   chmod +x deploy-secondary.sh
   ./deploy-secondary.sh latest http://CELSTATE_IP:8080 API_KEY bowlister
   ```

4. Verify on celsate:
   - Go to **Nodes**
   - bowlister should show as "Online"

## Upgrading

### Primary Node
```bash
cd /opt/powerblockade
POWERBLOCKADE_VERSION=v0.7.0 docker compose pull
POWERBLOCKADE_VERSION=v0.7.0 docker compose up -d


### Secondary Node
```bash
cd /opt/powerblockade
POWERBLOCKADE_VERSION=v0.7.0 docker compose pull
POWERBLOCKADE_VERSION=v0.7.0 docker compose --profile secondary up -d
```

### Recommended: Upgrade Secondaries First
To minimize disruption, upgrade secondaries before the primary:
1. Upgrade bowlister
2. Verify it's online and syncing
3. Upgrade celsate

## Version Pinning

Always pin to a specific version in production:

```bash
# Pin to specific version
export POWERBLOCKADE_VERSION=v0.7.0
docker compose up -d

# Or inline
POWERBLOCKADE_VERSION=v0.7.0 docker compose up -d

## Troubleshooting

### Secondary shows offline
```bash
# Check sync-agent logs
docker compose logs sync-agent

# Test connectivity to primary
curl -I http://PRIMARY_IP:8080/health
```

### DNS not working
```bash
# Test locally
dig @localhost google.com

# Check dnsdist logs
docker compose logs dnsdist

# Check recursor logs
docker compose logs recursor
```

### Permission errors
```bash
# Restart to re-run init-permissions
docker compose down
docker compose up -d
```

## Environment Variables

Key variables in `.env`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `POWERBLOCKADE_VERSION` | Image version | `latest` |
| `POWERBLOCKADE_REPO` | GHCR repo/org | `zerostate-io` |
| `DOCKER_SUBNET` | Docker network | `172.30.0.0/24` |
| `NODE_NAME` | Node identifier | `primary` |
| `PRIMARY_URL` | Primary API URL | (required on secondary) |
| `PRIMARY_API_KEY` | Auth to primary | (required on secondary) |
| `HEARTBEAT_INTERVAL_SECONDS` | Heartbeat frequency | `60` |

## Files

- `docker-compose.yml` - Downloaded from `docker-compose.ghcr.yml`
- `.env` - Generated with secure passwords
- `recursor/` - PowerDNS Recursor configs
- `dnsdist/` - DNS frontend configs
- `grafana/` - Dashboard provisioning
- `prometheus/` - Metrics config


## Rollback Procedures

For detailed rollback command packs with pre-rollback snapshots, exact command sequences, and post-rollback health checks, see:

**[Rollback Command Packs](../docs/performance/dns-cache-operations-runbook.md#rollback-command-packs)**

### Quick Rollback Reference

#### Secondary Node (bowlister)
```bash
# SSH to bowlister
cd /opt/powerblockade

# Get previous version from state
PREV_VERSION=$(jq -r '.previous_version' .powerblockade/state.json)

# Rollback
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose pull
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose --profile secondary up -d

# Verify
docker compose ps
dig @127.0.0.1 google.com +short
```

#### Primary Node (celsate)
```bash
# SSH to celsate
cd /opt/powerblockade

# Get previous version and backup location
PREV_VERSION=$(jq -r '.previous_version' .powerblockade/state.json)
DB_BACKUP=$(jq -r '.last_db_backup' .powerblockade/state.json)

# Rollback with database restore
docker compose down
docker compose up -d postgres
sleep 5
docker compose exec -T postgres psql -U powerblockade -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" powerblockade
docker compose exec -T postgres psql -U powerblockade powerblockade < "$DB_BACKUP"
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose pull
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose up -d

# Verify
curl -sf http://localhost:8080/health
dig @127.0.0.1 google.com +short
```

### Rollback Order

**Always rollback secondaries FIRST, then primary:**
1. Rollback bowlister (secondary)
2. Verify bowlister is online and syncing
3. Rollback celsate (primary)
4. Verify all nodes show as online

---

## Related Documentation

- [Upgrade Guide](../docs/UPGRADE.md) - Detailed upgrade procedures and migration notes
- [Using Pre-built Images](../docs/USING_PREBUILT_IMAGES.md) - GHCR image configuration and troubleshooting

---

## GHCR Authentication (Required for Private Packages)

If the Docker images are stored in a private GitHub Container Registry, you must authenticate before pulling.

### Step 1: Create a GitHub Token

1. Go to https://github.com/settings/tokens
2. Generate a **Personal access token (classic)**
3. Select the `read:packages` scope
4. Copy the token

### Step 2: Login to GHCR on Each Server

```bash
# Replace YOUR_TOKEN with your GitHub token
# Replace YOUR_USERNAME with your GitHub username
echo "YOUR_TOKEN" | docker login ghcr.io -u YOUR_USERNAME --password-stdin
```

### Step 3: Verify Access

```bash
docker pull ghcr.io/zerostate-io/powerblockade-admin-ui:v0.5.5
```

If this succeeds, you're authenticated and can proceed with deployment.

### Make Packages Public (Alternative)

For open-source projects, you can make packages public:

1. Go to https://github.com/orgs/Zerostate-IO/packages
2. For each `powerblockade-*` package:
   - Click the package → Package settings → Change visibility → **Public**

Public packages can be pulled without authentication.
