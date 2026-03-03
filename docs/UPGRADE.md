# Upgrading PowerBlockade

This guide covers how to upgrade PowerBlockade safely using pre-built Docker images from GitHub Container Registry (GHCR).

> 📖 **See [Release Policy](RELEASE_POLICY.md)** for version compatibility guarantees and what changes require manual intervention.

## Quick Upgrade (Prebuilt Images)

### Standard Upgrade

```bash
cd /path/to/powerblockade

# Pull latest images
docker compose -f docker-compose.ghcr.yml pull

# Restart with new images
docker compose -f docker-compose.ghcr.yml up -d
```

### Version-Pinned Upgrade (Recommended for Production)

Always pin to a specific version in production:

```bash
# Pin to a specific release
export POWERBLOCKADE_VERSION=v0.7.0

# Pull and restart
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

Or in a single command:

```bash
POWERBLOCKADE_VERSION=v0.7.0 docker compose -f docker-compose.ghcr.yml pull && \
POWERBLOCKADE_VERSION=v0.7.0 docker compose -f docker-compose.ghcr.yml up -d
```

## Migration Guide

If you're upgrading from an older version of PowerBlockade, you may need to update your workflow. Here are the key changes:

### Setup Commands

The canonical setup path has been simplified:

| Old Command | New Command | Notes |
|-------------|-------------|-------|
| `docker compose --profile primary up -d` | `docker compose -f docker-compose.ghcr.yml up -d` | No profile needed; primary is default |
| `docker compose --profile primary pull` | `docker compose -f docker-compose.ghcr.yml pull` | Use ghcr compose file for pre-built images |

### Environment Setup

The manual secret generation workflow has been replaced with an interactive script:

| Old Workflow | New Workflow | Notes |
|--------------|--------------|-------|
| Manual `generate_password()` in shell | `./scripts/init-env.sh` | Script handles all secrets |
| Manual `sed` commands in .env | `./scripts/init-env.sh` | Interactive prompts |
| Multiple setup paths | Single canonical path | Reduces confusion |

**Old (deprecated) approach:**
```bash
# This manual workflow is deprecated
ADMIN_PASSWORD=$(openssl rand -base64 24)
sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$ADMIN_PASSWORD/" .env
```

**New (recommended) approach:**
```bash
./scripts/init-env.sh  # Handles all secrets interactively
```

### Automation / CI/CD

For non-interactive setups (CI/CD, scripts):

```bash
./scripts/init-env.sh --non-interactive
```

This generates all secrets automatically without prompts, suitable for automated deployments.

### Secondary Nodes

Secondary node setup remains the same:

```bash
docker compose -f docker-compose.ghcr.yml --profile secondary up -d
```

The `--profile secondary` flag is still required for secondary nodes.

## Before You Upgrade

### 1. Check the Release Notes

Review the [CHANGELOG.md](../CHANGELOG.md) for:
- Breaking changes (require manual steps)
- New features (may need configuration)
- Bug fixes (what's being resolved)

### 2. Verify Your Version

```bash
# Check current version
docker compose -f docker-compose.ghcr.yml exec admin-ui cat /app/version.txt

# Or check in the UI: System Health → Version Info
```

### 3. Backup Your Data

The upgrade process preserves your data, but it's good practice to have a backup:

```bash
# Quick database backup
docker compose -f docker-compose.ghcr.yml exec postgres pg_dump -U powerblockade powerblockade > backup_$(date +%Y%m%d).sql
```

### 4. Check Node Status (Multi-Node Deployments)

If running secondary nodes, verify they're healthy:

1. Go to **Nodes** in the Admin UI
2. Confirm all nodes show "Online"
3. If any are offline, resolve issues before upgrading

## Upgrade Types

### Patch Upgrades (0.0.X → 0.0.Y)

**Always safe** - no manual steps required.

```bash
# Example: v0.7.0 → v0.7.1
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

Patch releases contain only:
- Bug fixes
- Performance improvements
- Documentation updates
- Minor UI improvements

### Minor Feature Upgrades (0.X.0 → 0.Y.0)

**Usually safe** - check release notes for any required steps.

```bash
# Example: v0.6.9 → v0.7.0
# 1. Read release notes first!
# 2. Check for new .env variables
# 3. Pull and restart
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

Feature releases may include:
- New configuration options
- New services or containers
- Database schema changes (auto-migrated)
- New API endpoints

### Major Upgrades (X.0.0 → Y.0.0)

**Read release notes carefully** - may require migration steps.

Major releases are reserved for:
- Architecture changes
- Breaking API changes
- Configuration format changes
- Database migration requirements

## PowerDNS Component Upgrade Notes (v0.7.0+)

When upgrading PowerDNS components (Recursor/dnsdist), the stack now includes built-in settings migration for Recursor old keys.

### Automatic migration behavior

- `scripts/pb update` migrates `recursor/recursor.conf.template` after DB migrations and before restart.
- `deploy/upgrade.sh` migrates `recursor/recursor.conf.template` before image pull/restart.
- `recursor/docker-entrypoint.sh` runs migration at startup as a fallback safety net.
- In-place migration writes a backup at `recursor/recursor.conf.template.bak.pre-migration`.

### Code updates required when bumping PowerDNS components

- Update upstream image lines in `compose.yaml` and `docker-compose.ghcr.yml` for `dnsdist` and `recursor-reloader`.
- Update Recursor base image in `recursor/Dockerfile`.
- Keep generated secondary package in sync via `admin-ui/app/services/node_generator.py`.
- Validate tuned settings in `recursor/recursor.conf.template` and `dnsdist/dnsdist.conf.template` against target versions.

### Documentation updates required when bumping PowerDNS components

- Add release notes in `CHANGELOG.md` (including operator actions if needed).
- Update upgrade examples in `docs/UPGRADE.md`, `QUICK_START.md`, and `deploy/README.md` for the new target version.
- If compatibility expectations changed, update `docs/COMPATIBILITY_MATRIX.md`.

## After You Upgrade

### 1. Verify Services Are Running

```bash
docker compose -f docker-compose.ghcr.yml ps
```

All containers should show `Up` or `healthy`.

### 2. Check the Admin UI

1. Open http://your-server:8080
2. Verify you can log in
3. Go to **System Health** → check version is updated
4. Check for any health warnings

### 3. Verify DNS Resolution

```bash
# Test DNS is working
dig @localhost google.com

# Test blocking is working
dig @localhost ad.doubleclick.net
```

### 4. Check Query Logs

1. Go to **Logs** in the Admin UI
2. Make some DNS queries
3. Verify they appear in the logs

### 5. For Multi-Node: Verify Sync

1. Go to **Nodes** in the Admin UI
2. Confirm all secondaries show "Online"
3. Check sync-agent logs on secondaries: `docker compose logs sync-agent`

## Rollback

If something goes wrong after an upgrade:

### Quick Rollback

```bash
# Roll back to previous version
export POWERBLOCKADE_VERSION=v0.6.9  # Your previous version

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

### Database Rollback

If you need to restore the database:

```bash
# Stop services
docker compose -f docker-compose.ghcr.yml down

# Restore from backup
cat backup_20250225.sql | docker compose -f docker-compose.ghcr.yml exec -T postgres psql -U powerblockade powerblockade

# Start services
docker compose -f docker-compose.ghcr.yml up -d
```

### Manual Rollback Procedure

> ⚠️ **Important**: `pb rollback` restores config and database but does NOT pull previous Docker images. If you need to restore a previous version completely, follow this procedure.

When rolling back to a previous version, you must explicitly pull the old images:

```bash
# 1. Get the previous version from state file
PREV_VERSION=$(jq -r '.previous_version' .powerblockade/state.json)
echo "Rolling back to: $PREV_VERSION"

# 2. Export the version and pull old images
export POWERBLOCKADE_VERSION="$PREV_VERSION"
docker compose -f docker-compose.ghcr.yml pull

# 3. Stop current containers
docker compose -f docker-compose.ghcr.yml down

# 4. Start with the old version
docker compose -f docker-compose.ghcr.yml up -d

# 5. Verify the rollback
docker exec admin-ui cat /app/version.txt
```

**Why this is needed**: The `pb rollback` command restores your database backup and configuration, but containers using `:latest` tags will restart with the same image. Explicit version pinning ensures you're running the intended version.

## Updating Config Files

Some updates may require updated configuration files (e.g., new prometheus.yml settings). Download the latest:

```bash
# Download updated config files (review changes first!)
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/prometheus/prometheus.yml -o prometheus/prometheus.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/grafana/provisioning/datasources/prometheus.yml -o grafana/provisioning/datasources/prometheus.yml

# Then restart
docker compose -f docker-compose.ghcr.yml up -d
```

## New Environment Variables

Feature releases may introduce new environment variables. Check `.env.example` for new options:

```bash
# Download latest example
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/.env.example -o .env.example.new

# Compare with your current .env
diff .env .env.example.new

# Add any new required variables to your .env
```

## Upgrading Secondary Nodes

For multi-node deployments, upgrade secondaries **before** the primary to minimize disruption:

1. **Upgrade secondaries first**: Each secondary can be upgraded independently
2. **Then upgrade primary**: After all secondaries are healthy

```bash
# On each secondary
POWERBLOCKADE_VERSION=v0.7.0 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=v0.7.0 docker compose -f docker-compose.ghcr.yml up -d

# Verify sync-agent is running
docker compose -f docker-compose.ghcr.yml logs sync-agent

# Then on primary
POWERBLOCKADE_VERSION=v0.7.0 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=v0.7.0 docker compose -f docker-compose.ghcr.yml up -d
```

## Manual Intervention Required

Some upgrades require manual steps. These are **always**:
1. Called out in the release notes
2. Only in feature or major releases (never patches)
3. Listed under "Operator Action Required" in CHANGELOG.md

Common manual steps include:
- Adding new environment variables
- Running database migrations explicitly
- Updating configuration files
- Clearing cached data

> ⚠️ **Never skip manual steps** - doing so may cause the system to fail or behave unexpectedly.

## Using the `pb` CLI (Git Clone Method)

If you cloned the repository, use the included CLI:

```bash
# Check for updates
./scripts/pb check-update

# Update to latest version
./scripts/pb update

# Rollback if needed
./scripts/pb rollback

# View current status
./scripts/pb status
```

The `pb` CLI handles:
- Automatic database backup before updates
- Pulling new Docker images
- Running database migrations
- Health verification
- Rollback on failure

## Troubleshooting

### Container won't start after upgrade

```bash
# Check logs
docker compose -f docker-compose.ghcr.yml logs admin-ui
docker compose -f docker-compose.ghcr.yml logs postgres

# Common issues:
# - Missing env var: Add to .env and restart
# - Database migration failed: Check postgres logs, may need manual intervention
# - Permission issues: Restart stack to re-run init-permissions
```

### Database migration errors

```bash
# Check current migration version
docker compose -f docker-compose.ghcr.yml exec admin-ui alembic current

# View migration history
docker compose -f docker-compose.ghcr.yml exec admin-ui alembic history

# If stuck, you may need to manually mark migration as complete (last resort)
# docker compose exec admin-ui alembic stamp head
```

### Secondary nodes not syncing after upgrade

```bash
# On secondary, check sync-agent
docker compose -f docker-compose.ghcr.yml logs sync-agent

# Verify PRIMARY_URL is correct
docker compose -f docker-compose.ghcr.yml exec sync-agent env | grep PRIMARY_URL

# Restart sync-agent
docker compose -f docker-compose.ghcr.yml restart sync-agent
```

### Rollback failed

1. Stop everything: `docker compose -f docker-compose.ghcr.yml down`
2. Restore database from backup (see Database Rollback above)
3. Start with old version: `POWERBLOCKADE_VERSION=v0.6.9 docker compose -f docker-compose.ghcr.yml up -d`

## Best Practices

1. **Pin versions in production** - Never use `:latest` tag in production
2. **Read release notes** - Always check CHANGELOG.md before upgrading
3. **Backup before upgrade** - Quick pg_dump takes seconds
4. **Upgrade during maintenance windows** - Even though upgrades are fast, do them when impact is minimal
5. **Test in staging** - If you have a staging environment, upgrade it first
6. **Monitor after upgrade** - Check logs and health for a few hours after

## Getting Help

- **GitHub Issues**: Report upgrade problems at https://github.com/Zerostate-IO/PowerBlockade/issues
- **In-app Help**: Click "Help" in the navigation for contextual documentation
- **System Health**: Check `/system` for detailed diagnostics
