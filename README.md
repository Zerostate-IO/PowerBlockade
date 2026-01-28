# PowerBlockade

Modern, performant DNS filtering stack built around **PowerDNS Recursor** with full query logging, metrics (Prometheus/Grafana), and optional multi-node redundancy.

Modern dark UI, multi-node support, Docker-first.

> **New to PowerBlockade?** See the [Getting Started Guide](docs/GETTING_STARTED.md) for a complete walkthrough including Docker installation, initial setup, and understanding the interface.

## Quick start (single-node)

### Option 1: Use pre-built images (faster, no build)

1. Set your GitHub username or org where images are hosted:

```bash
export POWERBLOCKADE_REPO=powerblockade  # Replace with your GitHub hosting repo
```

2. Generate `.env`:

```bash
./scripts/init-env.sh
```

3. Start the stack with pre-built images:

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

[Read more about pre-built images](docs/USING_PREBUILT_IMAGES.md)

### Option 2: Build locally (for development)

1. Generate `.env`:

```bash
./scripts/init-env.sh
```

2. Start the stack and build images:

```bash
docker compose up -d --build
```

## Access

- **Admin UI**: http://localhost:8080 (single entry point)
- **Grafana**: http://localhost:8080/grafana (proxied through admin-ui)
- **DNS**: UDP/TCP 53 on the host (via dnsdist)

### First Login

Default credentials (set in `.env`):
- Username: `admin` (or `ADMIN_USERNAME`)
- Password: your `ADMIN_PASSWORD` value

## Repo layout

```
powerblockade/
├── admin-ui/           # FastAPI + Jinja2 + SQLAlchemy (main UI)
├── dnstap-processor/   # Go service: dnstap → Admin API → Postgres
├── recursor/           # PowerDNS Recursor config + RPZ zones
├── dnsdist/            # Edge DNS proxy (client IP attribution)
├── sync-agent/         # Secondary node sync (via --profile sync-agent)
├── grafana/            # Dashboard provisioning
├── prometheus/         # Metrics scraping
└── scripts/            # init-env.sh
```

## Features

- **Blocklist management** - Import from URL (hosts, domains, adblock formats)
- **Query logging** - Real-time DNS query logs with filtering
- **Analytics dashboard** - Charts for queries, blocks, cache hits
- **Multi-node support** - Secondary nodes sync config from primary
- **Health monitoring** - Warnings with actionable remediation
- **Config rollback** - Audit trail with one-click rollback
- **Easy updates** - Pi-hole-like `pb update` CLI for upgrades

## Updating

Use the `pb` CLI for updates:

```bash
./scripts/pb check-update   # Check for available updates
./scripts/pb update         # Update to latest version
./scripts/pb rollback       # Rollback if needed
./scripts/pb status         # Show current status
```

The update system automatically backs up your database before upgrading.

## Customizing

To customize ports, networks, or other settings without losing changes on update:

1. Copy `compose.user.yaml.example` to `compose.user.yaml`
2. Add your customizations to `compose.user.yaml`
3. Run with: `docker compose -f compose.yaml -f compose.user.yaml up -d`

Your customizations in `compose.user.yaml` are never overwritten by updates.

## Security notes (prod)

- Set strong values in `.env` (do not commit it)
- Admin password is bootstrapped from `ADMIN_PASSWORD` on first run

## Optional profiles

```bash
# Enable secondary node sync agent
docker compose --profile sync-agent up -d

# Enable Traefik for TLS
DOMAIN=dns.example.com ACME_EMAIL=admin@example.com docker compose --profile traefik up -d
```

## Optional networking (prod)

- **macvlan "appliance mode" (Linux wired):** run `dnsdist` on a real LAN IP (no port publishing)
  - See: `docs/networking-macvlan.md`
