# Using Pre-Built Docker Images

PowerBlockade provides pre-built Docker images hosted on GitHub Container Registry (GHCR). You can pull these images instead of building locally.

## Quick Start with Pre-Built Images

### 1. Generate environment file

```bash
./scripts/init-env.sh
```

This creates `.env` with secure random values and sets `POWERBLOCKADE_REPO=zerostate-io` (the official image registry).

### 2. Start with pre-built images
```bash
docker compose -f docker-compose.ghcr.yml up -d
```

The `-f docker-compose.ghcr.yml` flag tells Docker Compose to use the configuration file with pre-built images.

### 3. (Optional) Secondary Node Setup


For secondary nodes in a multi-node deployment, use the `--profile secondary` flag:

```bash
docker compose -f docker-compose.ghcr.yml --profile secondary up -d
```

Secondary nodes only run the DNS services (dnsdist, recursor, dnstap-processor) and sync-agent. They do not run postgres, admin-ui, prometheus, or grafana - those run only on the primary node.

See [GETTING_STARTED.md](GETTING_STARTED.md#multi-node-setup-optional) for complete multi-node setup instructions.

## Repository Configuration

PowerBlockade uses GitHub Container Registry (GHCR) for pre-built images. The `POWERBLOCKADE_REPO` variable controls which registry to pull from.

### Default: Official Images

By default, `init-env.sh` sets:

```bash
POWERBLOCKADE_REPO=zerostate-io
```

This pulls images from `ghcr.io/zerostate-io/powerblockade-*:latest`.

### Override: Custom Registry

To use images from your own fork or registry, set the variable before running:

```bash
export POWERBLOCKADE_REPO=your-github-org
./scripts/init-env.sh
```

Or edit `.env` after running init-env.sh:

```bash
./scripts/init-env.sh
# Edit POWERBLOCKADE_REPO in .env if needed
docker compose -f docker-compose.ghcr.yml up -d
```

## Environment Variables Required for GHCR

| Variable | Description | Default |
|----------|-------------|---------|
| `POWERBLOCKADE_REPO` | GitHub org hosting images | `zerostate-io` |
| `POSTGRES_PASSWORD` | PostgreSQL password | (auto-generated) |
| `ADMIN_PASSWORD` | Admin UI password | (auto-generated) |
| `ADMIN_SECRET_KEY` | Session signing key | (auto-generated) |
| `RECURSOR_API_KEY` | Recursor API key | (auto-generated) |
| `PRIMARY_API_KEY` | Primary node API key | (auto-generated) |

## Available Images

| Image | GHCR Path | Description |
|-------|-----------|-------------|
| `powerblockade-recursor` | `ghcr.io/USER/powerblockade-recursor:latest` | PowerDNS Recursor with config |
| `powerblockade-dnstap-processor` | `ghcr.io/USER/powerblockade-dnstap-processor:latest` | Go service for DNS query ingestion |
| `powerblockade-admin-ui` | `ghcr.io/USER/powerblockade-admin-ui:latest` | FastAPI admin web interface |

## Image Tags

Images are tagged as follows:

- `latest` - Latest stable release from main branch
- `main-<git-sha>` - Specific commit from main branch
- `develop-<git-sha>` - Latest from develop branch

## Building vs. Pulling

### When to use `docker-compose.yml` (build locally):
- You're developing PowerBlockade
- You've made custom changes to the code
- You want the absolute latest changes

### When to use `docker-compose.ghcr.yml` (pull pre-built):
- You're a user who wants to get running quickly
- You don't need to modify the code
- You want faster deployment (no build time)

## Complete Comparison

```bash
# Build locally (slower, runs on your machine)
docker compose up -d --build

# Pull pre-built (faster, no build required)
./scripts/init-env.sh
docker compose -f docker-compose.ghcr.yml up -d
```

## First-Time Setup

If pulling pre-built images for the first time:

```bash
# 1. Clone the repository
git clone https://github.com/zerostate-io/powerblockade.git
cd powerblockade

# 2. Generate secrets (sets POWERBLOCKADE_REPO=zerostate-io by default)
./scripts/init-env.sh

# 3. (Optional) Override registry if using custom images
# export POWERBLOCKADE_REPO=your-org

# 4. Start the stack
docker compose -f docker-compose.ghcr.yml up -d
```

## Troubleshooting

### Images won't pull

Make sure:
1. The `POWERBLOCKADE_REPO` variable matches your registry (default: `zerostate-io`)
2. You've set the image tag version in `docker-compose.ghcr.yml`
3. Your GitHub repository is public (or you're authenticated)

```bash
# Verify image is accessible (using default repo)
docker pull ghcr.io/zerostate-io/powerblockade-admin-ui:latest
```

### Wrong image tag

If you need a specific version of an image, edit `docker-compose.ghcr.yml` and change `:latest` to a specific tag:

```yaml
recursor:
  image: ghcr.io/ORG/powerblockade-recursor:main-abc123
```

### Access denied

If you get authentication errors, log in to GHCR:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

## Private Repositories

If PowerBlockade images are in a private repository:

1. Create a GitHub Personal Access Token (PAT) with `read:packages` scope
2. Log in to GHCR:

```bash
docker login ghcr.io
# Username: YOUR_GITHUB_USERNAME
# Password: YOUR_GITHUB_TOKEN
```

## CI/CD Integration

The `.github/workflows/docker-build.yml` workflow automatically:

1. Builds Docker images when code changes are pushed to main/develop
2. Pushes images to GHCR with appropriate tags (`latest`, `main-<sha>`, `develop-<sha>`)
3. Uses GitHub Actions cache for faster subsequent builds

No manual intervention required - images are built and published automatically.

## Updating Pre-Built Images

When a new image is published:

```bash
# Pull latest images
docker compose -f docker-compose.ghcr.yml pull

# Restart containers with new images
docker compose -f docker-compose.ghcr.yml up -d
```