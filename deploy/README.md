# PowerBlockade Deployment Guide

This directory contains scripts for deploying PowerBlockade to production servers using pre-built Docker images from GitHub Container Registry (GHCR).

## Quick Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `deploy-primary-one-liner.sh` | Interactive single-host easy start | `curl -fsSL .../deploy-primary-one-liner.sh \| bash` |
| `deploy-primary.sh` | Deploy primary node | `./deploy-primary.sh [version]` |
| `deploy-secondary.sh` | Deploy secondary node | `./deploy-secondary.sh [version] [primary_url] [api_key] [node_name]` |
| `upgrade.sh` | Upgrade existing deployment | `./upgrade.sh [version]` |

## Single-Host Easy Start

For a brand-new single node, use:

```bash
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary-one-liner.sh | bash
```

Optional version pin:

```bash
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary-one-liner.sh | bash -s -- v0.7.8
```

This flow is interactive and includes prerequisites, Docker/Compose setup, `init-env.sh` prompts, and startup checks.

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

1. **Clone the repository on celsate:**
   ```bash
   git clone https://github.com/Zerostate-IO/PowerBlockade.git /opt/powerblockade
   cd /opt/powerblockade
   ```

2. **Generate secrets and configure:**
   ```bash
   ./scripts/init-env.sh
   ```

3. **Start with pre-built images:**
   ```bash
POWERBLOCKADE_VERSION=0.7.8 docker compose -f docker-compose.ghcr.yml up -d
   ```

4. Note the generated admin password from the `init-env.sh` output.

5. Access the Admin UI at `http://celsate:8080`

6. Go to **Nodes** → **Add Node** to register bowlister.

## Deploy Secondary Node (bowlister)

1. On celsate, generate a node package:
   - Go to **Nodes** → **Add Node**
   - Enter name: `bowlister`
   - Click **Generate Deployment Package**
   - Note the API key

2. **Clone the repository on bowlister:**
   ```bash
   git clone https://github.com/Zerostate-IO/PowerBlockade.git /opt/powerblockade
   cd /opt/powerblockade
   ./scripts/init-env.sh
   ```
   Set `NODE_NAME=bowlister`, `PRIMARY_URL=http://CELSATE_IP:8080`, and `PRIMARY_API_KEY` in `.env`.

3. **Start the secondary stack:**
   ```bash
POWERBLOCKADE_VERSION=0.7.8 docker compose -f docker-compose.ghcr.yml --profile secondary up -d
   ```

4. Verify on celsate:
   - Go to **Nodes**
   - bowlister should show as "Online"

## Upgrading

### Primary Node
```bash
cd /opt/powerblockade
POWERBLOCKADE_VERSION=0.7.8 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.8 docker compose -f docker-compose.ghcr.yml up -d
```


### Secondary Node
```bash
cd /opt/powerblockade
POWERBLOCKADE_VERSION=0.7.8 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.8 docker compose -f docker-compose.ghcr.yml --profile secondary up -d
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
export POWERBLOCKADE_VERSION=0.7.8
docker compose -f docker-compose.ghcr.yml up -d

# Or inline
POWERBLOCKADE_VERSION=0.7.8 docker compose -f docker-compose.ghcr.yml up -d
```

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
# Test the configured bind address
dig @YOUR_DNSDIST_LISTEN_ADDRESS google.com

# Check dnsdist logs
docker compose logs dnsdist

# Check recursor logs
docker compose logs recursor
```

### DNS unreachable after reboot
```bash
# Confirm the DNS services actually recovered
docker compose ps recursor dnsdist

# Test the configured serving address, not a VPN helper address
dig @YOUR_DNSDIST_LISTEN_ADDRESS google.com +short

# If recursor is healthy but dnsdist is still starting or unhealthy,
# inspect the startup ordering and readiness logs
docker compose logs dnsdist | tail -50

# Force the stack back through the intended dependency order
docker compose restart recursor
sleep 10
docker compose restart dnsdist
```

If queries only succeed on a Netbird or Tailscale IP, verify that you are not accidentally testing the VPN resolver instead of PowerBlockade's configured `DNSDIST_LISTEN_ADDRESS`. `127.0.0.1` may legitimately refuse if dnsdist is published only on a specific LAN IP.

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
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose -f docker-compose.ghcr.yml --profile secondary up -d

# Verify
docker compose -f docker-compose.ghcr.yml ps
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
docker compose -f docker-compose.ghcr.yml down
docker compose -f docker-compose.ghcr.yml up -d postgres
sleep 5
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" powerblockade
docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade powerblockade < "$DB_BACKUP"
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION="$PREV_VERSION" docker compose -f docker-compose.ghcr.yml up -d

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
docker pull ghcr.io/zerostate-io/powerblockade-admin-ui:latest
```

If this succeeds, you're authenticated and can proceed with deployment.

### Make Packages Public (Alternative)

For open-source projects, you can make packages public:

1. Go to https://github.com/orgs/Zerostate-IO/packages
2. For each `powerblockade-*` package:
   - Click the package → Package settings → Change visibility → **Public**

Public packages can be pulled without authentication.
