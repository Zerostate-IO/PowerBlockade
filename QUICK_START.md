# PowerBlockade Quick Start

Get a DNS filtering server running in under 5 minutes using pre-built Docker images.

> **Looking for more detail?** See [Getting Started](docs/GETTING_STARTED.md) for a complete walkthrough, or [Upgrade Guide](docs/UPGRADE.md) for updating an existing installation.

## One-Command Easy Start (Single Host)

For a brand-new Linux host, run:

```bash
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary-one-liner.sh | bash
```

Optional version pin:

```bash
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary-one-liner.sh | bash -s -- v0.7.0
```

The installer asks questions, detects missing prerequisites, handles Docker/Compose installation, runs `init-env.sh`, and starts the stack.

For full details, see [docs/EASY_START.md](docs/EASY_START.md).

## Manual Walkthrough

## Network Topology Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Your Network                            │
│                                                                 │
│  ┌─────────────┐     ┌──────────────────────────────────────┐  │
│  │   Router/   │     │     Docker Host (PowerBlockade)       │  │
│  │   Firewall  │     │                                      │  │
│  │             │     │  ┌─────────────────────────────────┐ │  │
│  │  DHCP:      │────▶│  │ dnsdist (port 53)               │ │  │
│  │  DNS Server │     │  │    └─▶ recursor └─▶ internet    │ │  │
│  │  = 192.168. │     │  │                                  │ │  │
│  │    1.10     │     │  │  admin-ui (port 8080)            │ │  │
│  └─────┬───────┘     │  │    └─▶ Grafana dashboards        │ │  │
│        │             │  │                                  │ │  │
│        ▼             │  │  postgres, prometheus, etc.      │ │  │
│  ┌─────────────┐     │  └─────────────────────────────────┘ │  │
│  │   Clients   │     │                                      │  │
│  │  (phones,   │◀────│  IP: 192.168.1.10                    │  │
│  │   laptops,  │     │                                      │  │
│  │   etc.)     │     └──────────────────────────────────────┘  │
│  └─────────────┘                                                │
│                                                                 │
│  DNS queries: Client → Router → PowerBlockade → Internet       │
│  Blocked ads/malware: PowerBlockade returns NXDOMAIN           │
└─────────────────────────────────────────────────────────────────┘
```

## Requirements

- **Docker & Docker Compose** (v2+)
- **A Linux server** (Ubuntu 22.04+ recommended)
- **Port 53** available for DNS (or see port conflict handling below)
- **Port 8080** available for Admin UI
- **Git** for cloning the repository

## Step 0: GHCR Authentication (If Images Are Private)

If the Docker images are stored in a private GitHub Container Registry, authenticate first.

**Quick test:**
```bash
docker pull ghcr.io/zerostate-io/powerblockade-admin-ui:latest
```

- **If this works:** Skip to Step 1 (images are public)
- **If you get "403 Forbidden":** Images are private, authenticate below

**Authenticate to GHCR:**

1. Create a GitHub token with `read:packages` scope:
   - Go to https://github.com/settings/tokens
   - Generate new token (classic)
   - Select `read:packages`
   - Copy the token

2. Login to GHCR:
   ```bash
   # Replace YOUR_TOKEN and YOUR_USERNAME
   echo "YOUR_TOKEN" | docker login ghcr.io -u YOUR_USERNAME --password-stdin
   ```

3. Verify access:
   ```bash
   docker pull ghcr.io/zerostate-io/powerblockade-admin-ui:latest
   ```

**Alternative:** Ask your organization admin to make the packages public at:
https://github.com/orgs/Zerostate-IO/packages

## Step 1: Clone the Repository

```bash
git clone https://github.com/Zerostate-IO/PowerBlockade.git
cd PowerBlockade
```

## Step 2: Run Interactive Setup

Run the setup script to configure your environment:

```bash
./scripts/init-env.sh
```

The script will guide you through:

### Port 53 Conflict Detection

The script automatically detects common port 53 conflicts:
- **systemd-resolved** (Ubuntu's default DNS stub resolver)
- **Netbird** (VPN DNS resolver)
- **Tailscale** (VPN DNS resolver)
- **dnsmasq** (DNS forwarder)
- **Pi-hole** (DNS server)

If a conflict is found, you can:
1. **Bind to a specific IP** (recommended) - DNS will only listen on that interface
2. **Keep binding to all interfaces** - May fail if port is in use
3. **Stop the conflicting service** - Script will attempt to stop it automatically

### Node Name

Enter a name for this node (default: `primary`). This is used for logging and multi-node setups.

### Admin Credentials

Choose how to set your admin password:
1. **Auto-generate** (recommended) - Creates a secure random password
2. **Custom password** - Enter your own (minimum 8 characters)

The script displays your credentials at the end. **Save your admin password** - it won't be shown again.

## Step 3: Start PowerBlockade

Start all services with pre-built images:

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

Wait about 30 seconds for all services to initialize.

### Verify the Stack

```bash
docker compose -f docker-compose.ghcr.yml ps
```

All containers should show `running` or `healthy`. If any are restarting:

```bash
docker compose -f docker-compose.ghcr.yml logs -f <service-name>
```

### Version Pinning (Recommended for Production)

To pin to a specific version instead of `latest`:

```bash
# Pin to a specific release
POWERBLOCKADE_VERSION=v0.7.0 docker compose -f docker-compose.ghcr.yml up -d
```

## Step 4: Access the Admin UI

- **Admin UI**: http://your-server:8080
- **Username**: `admin` (or what you set during setup)
- **Password**: (shown at the end of Step 2)

You can also view your password:
```bash
grep '^ADMIN_PASSWORD=' .env
```

## Step 5: Configure Your Network

### Option A: Router-Level DNS (Recommended)

Configure your router's DHCP to advertise your PowerBlockade server as the DNS server:

1. Log into your router's admin panel
2. Find **DHCP** or **LAN** settings
3. Set **DNS Server** to your PowerBlockade server's IP (e.g., `192.168.1.10`)
4. Save and apply changes
5. Reconnect devices (or wait for DHCP lease renewal)

All devices on your network will automatically use PowerBlockade for DNS.

### Option B: Per-Device DNS

Manually set the DNS server on each device to your PowerBlockade server's IP.

## Step 6: Verify DNS is Working

Test from any device on your network:

```bash
# Test DNS resolution (should return an IP)
dig @YOUR_SERVER_IP google.com

# Test blocking (should return NXDOMAIN if blocklists are active)
dig @YOUR_SERVER_IP ad.doubleclick.net
```

Or from the PowerBlockade server itself:

```bash
# Test locally
dig @localhost google.com
```

### Check Query Logs

1. Open the Admin UI at http://your-server:8080
2. Go to **Logs** in the navigation
3. Make some DNS queries from a device
4. You should see queries appearing in real-time

---

## Secondary Node Setup

For redundancy, deploy additional nodes that sync configuration from your primary:

```bash
# On the secondary node, clone and run setup
git clone https://github.com/Zerostate-IO/PowerBlockade.git
cd PowerBlockade
./scripts/init-env.sh

# Start with the secondary profile
docker compose -f docker-compose.ghcr.yml --profile secondary up -d
```

The secondary node will:
- Sync blocklists and configuration from the primary
- Handle DNS queries locally
- Buffer metrics if the primary is unavailable

See [Multi-Node Architecture](docs/MULTI_NODE_ARCHITECTURE.md) for full details.

---

## What's Running

| Service | Purpose |
|---------|---------|
| `dnsdist` | DNS frontend (port 53) - load balancing, rate limiting |
| `recursor` | PowerDNS resolver - handles actual DNS lookups |
| `admin-ui` | Web interface (port 8080) |
| `dnstap-processor` | Query logging - sends to admin-ui |
| `postgres` | Database for logs, config, analytics |
| `prometheus` | Metrics collection |
| `grafana` | Dashboards (embedded in admin-ui) |

## Common Tasks

### View logs

```bash
docker compose -f docker-compose.ghcr.yml logs -f admin-ui
docker compose -f docker-compose.ghcr.yml logs -f dnsdist
docker compose -f docker-compose.ghcr.yml logs -f recursor
```

### Stop everything

```bash
docker compose -f docker-compose.ghcr.yml down
```

### Update to latest version

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

### Update to a specific version

```bash
POWERBLOCKADE_VERSION=v0.7.0 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=v0.7.0 docker compose -f docker-compose.ghcr.yml up -d
```

### Check status

```bash
docker compose -f docker-compose.ghcr.yml ps
```

## Troubleshooting

### Port 53 already in use

The init script handles this automatically. If you need to change the bind address after setup:

```bash
# Edit .env
DNSDIST_LISTEN_ADDRESS=192.168.1.10  # Your server's LAN IP

# Restart
docker compose -f docker-compose.ghcr.yml down
docker compose -f docker-compose.ghcr.yml up -d
```

To manually check what's using port 53:
```bash
sudo lsof -i :53
```

### Can't connect to Admin UI

```bash
# Check if admin-ui is running
docker compose -f docker-compose.ghcr.yml ps admin-ui

# Check logs for errors
docker compose -f docker-compose.ghcr.yml logs admin-ui

# Check firewall allows port 8080
sudo ufw allow 8080/tcp
```

### DNS queries not working

```bash
# Test DNS resolution locally
dig @localhost google.com

# Check dnsdist logs
docker compose -f docker-compose.ghcr.yml logs dnsdist

# Check recursor logs
docker compose -f docker-compose.ghcr.yml logs recursor
```

### Docker network conflicts

If the default subnet (`172.30.0.0/24`) conflicts with your network:

```bash
# Check for conflicts
ip route | grep 172.30

# Edit .env to use a different subnet
# (The init script sets these, but you can override)
```

## Next Steps

1. **Add blocklists**: Go to **Blocklists** in the Admin UI → Click **Add Blocklist** → Choose a preset or enter a URL → Click **Apply**

2. **View analytics**: Go to **Dashboard** to see query counts, top domains, and block rates

3. **Name your clients**: Go to **Clients** to assign friendly names to devices based on IP or MAC

4. **Set up forward zones** (optional): Go to **Forward Zones** to route specific domains to internal DNS servers

5. **PTR records** (optional): If you need reverse DNS lookups for your internal network, see the [GETTING_STARTED guide](docs/GETTING_STARTED.md) for forward zone configuration

6. **Multi-node setup** (optional): For redundancy, see [Multi-Node Architecture](docs/MULTI_NODE_ARCHITECTURE.md)

---

For full documentation, see:
- [Getting Started Guide](docs/GETTING_STARTED.md) - Complete walkthrough
- [Upgrade Guide](docs/UPGRADE.md) - How to upgrade safely
- [Multi-Node Architecture](docs/MULTI_NODE_ARCHITECTURE.md) - High availability setup
- [Release Policy](docs/RELEASE_POLICY.md) - Version compatibility guarantees
