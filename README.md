# PowerBlockade

Modern, performant DNS filtering stack built around **PowerDNS Recursor** with full query logging, metrics (Prometheus/Grafana), and optional multi-node redundancy.

Modern dark UI, multi-node support, Docker-first.

> **New to PowerBlockade?** See the [Getting Started Guide](docs/GETTING_STARTED.md) for a complete walkthrough including Docker installation, initial setup, and understanding the interface.

## Quick start

### Easy Start (single host)

Paste this into a fresh Linux host:

```bash
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary-one-liner.sh | bash
```

The installer is interactive and handles dependency checks, Docker setup, repo checkout, `.env` generation, and startup.

See [Easy Start Guide](docs/EASY_START.md) for details.

### Manual setup path

The canonical manual setup path uses pre-built images from GitHub Container Registry:

```bash
./scripts/init-env.sh
docker compose -f docker-compose.ghcr.yml up -d
```

That's it. Two commands if Docker and prerequisites are already installed.

### What `init-env.sh` does

The setup script is interactive and will prompt you for:

1. **Port 53 handling** - Detects conflicts (systemd-resolved, Netbird, Tailscale, Pi-hole) and offers options
2. **Node name** - Defaults to `primary`
3. **Admin credentials** - Choose auto-generated or custom password

After completion, it prints your admin password. Save it.

### Verify the stack is running

```bash
docker compose -f docker-compose.ghcr.yml ps
```

All services should show `running` or `healthy`. If any are restarting, check logs:

```bash
docker compose -f docker-compose.ghcr.yml logs -f <service-name>
```

### Alternative: Build locally

For development or customization:

```bash
./scripts/init-env.sh
docker compose up -d --build
```

[Read more about pre-built images](docs/USING_PREBUILT_IMAGES.md)

## Documentation

- [Easy Start](docs/EASY_START.md) - One-command bootstrap for single-host installs
- [Quick Start Guide](QUICK_START.md) - Get running in 5 minutes
- [Getting Started](docs/GETTING_STARTED.md) - Complete walkthrough with Docker setup
- [Using Pre-built Images](docs/USING_PREBUILT_IMAGES.md) - GHCR image details

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

## Port 53 conflicts

If another service (like Netbird, systemd-resolved, or another DNS server) is using port 53, you can bind dnsdist to a specific IP instead of all interfaces:

```bash
# Add to .env
DNSDIST_LISTEN_ADDRESS=192.168.1.10  # Your server's LAN IP
```

This is common when running:
- **Netbird/Tailscale** - VPN software that runs its own DNS resolver
- **systemd-resolved** - Ubuntu's default DNS stub resolver (binds 127.0.0.53:53)
- **dnsmasq** - Often used by NetworkManager

## Optional networking (prod)

- **macvlan "appliance mode" (Linux wired):** run `dnsdist` on a real LAN IP (no port publishing)
  - See: `docs/networking-macvlan.md`
