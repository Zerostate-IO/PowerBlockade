# PowerBlockade Easy Start (Single Host)

Use this when you want a brand-new host to be fully set up with one command.

## One-Command Install

```bash
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary-one-liner.sh | bash
```

Optional: pin to a specific image tag:

```bash
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary-one-liner.sh | bash -s -- v0.7.0
```

## What The Installer Does

The script is interactive and handles full single-host bootstrap:

1. Detects Linux distro and package manager.
2. Detects missing prerequisites (`curl`, `git`, `openssl`) and offers to install them.
3. Detects Docker and Docker Compose; installs them when missing.
4. Verifies Docker daemon access and falls back to `sudo docker` when needed.
5. Clones (or updates) the PowerBlockade repo.
6. Runs `./scripts/init-env.sh` for guided environment setup:
   - Port 53 conflict detection and handling
   - Node name
   - Admin username/password
   - Secure secret generation
7. Pulls images and starts the stack with `docker-compose.ghcr.yml`.
8. Runs health checks and prints access credentials.

## Supported Target

- Linux hosts (production target)
- Single node / single host deployments

For multi-node deployments, use [QUICK_START.md](../QUICK_START.md) and [deploy/README.md](../deploy/README.md).

## After Install

The installer prints:

- Admin UI URL
- Admin username/password
- DNS bind address
- Useful follow-up commands (`ps`, `logs`, DNS test)

Then point your router DHCP DNS server to this host.

## Re-Running On The Same Host

Re-running the same command is safe for iterative setup:

- Existing git checkout: script offers to update it.
- Existing `.env`: `init-env.sh` updates values interactively.
- Existing containers: compose reconciles to desired state.

## Troubleshooting

If setup stops early:

1. Re-run the same installer command and accept fixes when prompted.
2. Check Docker daemon:
   ```bash
   docker info
   ```
3. Check service status:
   ```bash
   cd /opt/powerblockade
   docker compose -f docker-compose.ghcr.yml ps
   ```
4. Check admin logs:
   ```bash
   cd /opt/powerblockade
   docker compose -f docker-compose.ghcr.yml logs -f admin-ui
   ```
