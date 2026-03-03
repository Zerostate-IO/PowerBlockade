# Getting Started with PowerBlockade

A beginner's guide to setting up PowerBlockade as your network's DNS filter.

## What is PowerBlockade?

PowerBlockade is a modern alternative to Pi-hole for network-wide ad blocking and DNS filtering. It uses PowerDNS Recursor for high-performance DNS resolution with:

- Web-based admin UI for managing blocklists and viewing analytics
- Real-time query logging with client attribution
- Prometheus/Grafana metrics and dashboards
- Optional multi-node redundancy for high availability

## Requirements

### Supported Operating Systems

PowerBlockade is designed for **Linux servers**. Tested on:
- Ubuntu 22.04+ / Debian 12+
- Raspberry Pi OS (64-bit recommended)
- Any Linux with Docker support

> **Note**: macOS and Windows can run PowerBlockade for development/testing, but production deployments should use Linux.

### Hardware Requirements

| Deployment | CPU | RAM | Storage |
|------------|-----|-----|---------|
| Small home (< 10 devices) | 1 core | 512MB | 2GB |
| Medium home (10-50 devices) | 2 cores | 1GB | 5GB |
| Large network (50+ devices) | 4 cores | 2GB+ | 10GB+ |

PowerBlockade runs well on a Raspberry Pi 4 (2GB+ RAM recommended).

### Software Requirements

- **Docker** (v20.10+) and **Docker Compose** (v2.0+)
- **Git** (to clone the repository)
- Port 53 (DNS) available on the host

## Step 1: Install Docker

If Docker isn't installed, follow the official guides:

### Ubuntu/Debian

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install Docker using the convenience script
curl -fsSL https://get.docker.com | sudo sh

# Add your user to the docker group (logout/login after)
sudo usermod -aG docker $USER

# Verify installation
docker --version
docker compose version
```

### Raspberry Pi OS

```bash
# Same as Debian
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Enable Docker to start on boot
sudo systemctl enable docker
```

After adding yourself to the docker group, **log out and back in** for it to take effect.

## Step 2: Clone and Configure

```bash
# Clone the repository
git clone https://github.com/Zerostate-IO/PowerBlockade.git
cd PowerBlockade

# Run interactive setup script
./scripts/init-env.sh
```

The `init-env.sh` script is interactive and guides you through setup:

### Step 1: DNS Port Check

The script detects if port 53 is already in use by:
- **systemd-resolved** (Ubuntu's default DNS stub resolver)
- **Netbird** or **Tailscale** (VPN DNS resolvers)
- **dnsmasq** (often used by NetworkManager)
- **Pi-hole** or other DNS servers

If a conflict is found, you can:
1. **Bind to a specific IP** (recommended) - dnsdist will listen on just that interface
2. **Keep binding to all interfaces** - may fail if the port is in use
3. **Stop the conflicting service** - the script will stop it for you

### Step 2: Node Configuration

Enter a node name for this instance. Default is `primary`.

### Step 3: Admin Credentials

Choose how to set your admin password:
1. **Auto-generate** - Creates a secure random password (recommended)
2. **Custom password** - Enter your own (minimum 8 characters)

### Step 4: Secrets Generation

The script automatically generates secure random values for:
- `ADMIN_SECRET_KEY` - Session encryption key
- `POSTGRES_PASSWORD` - Database credentials
- `RECURSOR_API_KEY` - Recursor management API key
- `PRIMARY_API_KEY` - Internal API authentication
- `GRAFANA_ADMIN_PASSWORD` - Grafana login password

**Save the displayed admin password!** You'll need it to log in.

### (Optional) Review Configuration

```bash
# View generated config (don't share these values!)
cat .env
```
## Step 3: Start PowerBlockade

### Primary Path: Pre-built Images (Recommended)

Use pre-built images from GitHub Container Registry for fastest startup:

```bash
# Start with pre-built images (no local build needed)
docker compose -f docker-compose.ghcr.yml up -d
```

First startup takes 1-2 minutes to:
1. Pull container images from GHCR
2. Initialize the PostgreSQL database
3. Run database migrations
4. Start all services

### Alternative: Build Locally

For development or customization, build images locally:

```bash
# Build and start all services
docker compose up -d --build
```

This takes longer (2-5 minutes) as it builds all containers from source.

### Verify the Stack is Running

Check that everything is running:

```bash
# For pre-built images
docker compose -f docker-compose.ghcr.yml ps

# Or for local build
docker compose ps
```

All containers should show `Up` status:
- `powerblockade-admin-ui` - Web interface
- `powerblockade-postgres` - Database
- `powerblockade-recursor` - DNS resolver
- `powerblockade-dnsdist` - DNS frontend (port 53)
- `powerblockade-dnstap-processor` - Query logging
- `powerblockade-prometheus` - Metrics
- `powerblockade-grafana` - Dashboards

## Step 4: Access the Admin UI

Open your browser to: **http://YOUR_SERVER_IP:8080**

Login with:
- **Username**: `admin` (or your `ADMIN_USERNAME`)
- **Password**: The password shown when you ran `init-env.sh`

## Step 5: Initial Setup

After logging in, you'll see the Dashboard. Here's what to do first:

### 5.1 Add Blocklists

Go to **Blocklists** in the navigation bar.

1. Click **Add Blocklist**
2. Choose from popular presets or enter a custom URL:
   - **StevenBlack Hosts** - Comprehensive ad/malware blocking
   - **OISD** - Balanced blocking with minimal false positives
   - **Hagezi** - Privacy-focused lists
3. Click **Apply** to download and activate the blocklists

The system will download the lists, parse them, and generate RPZ zones. The recursor reloads automatically within ~5 seconds.

### 5.2 Point Your Devices to PowerBlockade

Change your devices' DNS server to your PowerBlockade server's IP address.

**Router-level (recommended)**: Configure your router's DHCP to advertise your PowerBlockade server as the DNS server. All devices on your network will use it automatically.

**Per-device**: Manually set DNS in each device's network settings.

### 5.3 Verify It's Working

1. Make some DNS queries from a device (browse the web)
2. Return to the **Dashboard** - you should see query counts increasing
3. Go to **Logs** to see real-time DNS queries
4. Check **Blocked** to see blocked queries

## Understanding the Interface

### Navigation Pages

| Page | Purpose |
|------|---------|
| **Dashboard** | Overview charts: queries over time, top domains, top clients, block rate |
| **Logs** | Real-time query log with search and filtering |
| **Clients** | List of clients making DNS queries with friendly names |
| **Domains** | Top queried domains ranked by frequency |
| **Blocked** | Log of blocked queries - what was blocked and why |
| **Failures** | DNS resolution failures (SERVFAIL, NXDOMAIN, timeouts) |
| **Blocklists** | Manage blocklist subscriptions and whitelist/blacklist entries |
| **Forward Zones** | Override DNS for specific domains (e.g., internal domains) |
| **Precache** | Cache warming settings to speed up common queries |
| **Nodes** | Multi-node management (for redundant setups) |
| **Audit** | Configuration change history with rollback capability |
| **Setup** | Quick setup wizard and system configuration |
| **System Health** | Grafana dashboards, version info, node metrics |

### Key Features Explained

**Blocklists**: Subscribe to blocklist URLs. PowerBlockade automatically downloads and updates them on schedule. Supports hosts files, domain lists, and AdBlock format.

**Whitelist/Blacklist**: Override blocklists for specific domains. Whitelist allows a blocked domain; blacklist blocks an allowed domain.

**Forward Zones**: Route specific domains to different DNS servers. Useful for:
- Internal company domains → internal DNS
- Split-horizon DNS setups
- Bypassing blocking for specific services

**Precache**: Aggressive cache warming pre-resolves your most common domains so they're instant when needed. Configurable from 100 to 100,000 domains.

**Audit Trail**: Every configuration change is logged. You can view what changed and roll back to previous configurations with one click.

## Updating PowerBlockade

PowerBlockade includes a Pi-hole-style update system:

```bash
cd /path/to/PowerBlockade

# Check for updates
./scripts/pb check-update

# Update to latest version (backs up database automatically)
./scripts/pb update

# If something goes wrong, rollback
./scripts/pb rollback

# View current status
./scripts/pb status
```

## Troubleshooting

### Port 53 Already in Use

If dnsdist fails to start because port 53 is in use:

```bash
# Find what's using port 53
sudo ss -tulpn | grep :53
```

Common culprits:
- **systemd-resolved**: Disable with `sudo systemctl disable --now systemd-resolved`
- **dnsmasq**: Stop with `sudo systemctl stop dnsmasq`
- **Another DNS server**: Stop or reconfigure it

### Docker Network Conflicts

PowerBlockade uses a dedicated Docker network (`172.30.0.0/24` by default). If this conflicts with your existing network infrastructure:

1. Check if the subnet is in use:
```bash
ip route | grep 172.30
```

2. If there's a conflict, edit `.env` and change the network settings:
```bash
# Choose an unused /24 subnet (e.g., 172.31.0.0/24)
DOCKER_SUBNET=172.31.0.0/24
RECURSOR_IP=172.31.0.10
DNSTAP_PROCESSOR_IP=172.31.0.20
```

3. Restart the stack:
```bash
docker compose down
docker compose up -d
```

> **Important**: All three values must be consistent - the IPs must be within the subnet range. The recursor and dnstap-processor need fixed IPs for dnstap logging.

### Container Won't Start

Check logs for the failing container:

```bash
docker compose logs admin-ui
docker compose logs recursor
docker compose logs dnsdist
```

### Blocklist Apply Fails with Permission Error

If clicking "Apply" on the Blocklists page returns a 500 error, the RPZ directory may have incorrect permissions:

```bash
# Fix permissions on the shared RPZ directory
sudo chmod -R 777 /path/to/PowerBlockade/recursor/rpz

# Or from inside the project
chmod -R 777 recursor/rpz
```

This can happen after pulling updates or if Docker created the directory as root.

### Database Issues

If the admin-ui shows database errors:

```bash
# Check postgres is healthy
docker compose ps postgres

# View postgres logs
docker compose logs postgres

# If needed, reset (WARNING: loses data)
docker compose down -v
docker compose up -d --build
```

### Can't Access Web UI

1. Verify the container is running: `docker compose ps admin-ui`
2. Check firewall allows port 8080: `sudo ufw allow 8080/tcp`
3. Try accessing locally first: `curl http://localhost:8080`

## Multi-Node Setup (Optional)

For high availability, you can run secondary nodes that sync from the primary.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Multi-Node Architecture                          │
│
│   ┌──────────────────────────────────────────────────────────────┐ │
│   │                    PRIMARY NODE                               │ │
│   │                                                               │ │
│   │  dnsdist ──▶ recursor ──▶ internet                           │ │
│   │     │                         │                               │ │
│   │     ▼                         ▼                               │ │
│   │  dnstap-processor         admin-ui (port 8080)               │ │
│   │     │                         │                               │ │
│   │     ▼                         ▼                               │ │
│   │  POST /api/node-sync/     postgres ──▶ grafana               │ │
│   │       ingest                 │      ──▶ prometheus            │ │
│   │                              │                               │ │
│   │                         ┌────┴────┐                          │ │
│   │                         │ Central │                          │ │
│   │                         │  Logs & │                          │ │
│   │                         │ Metrics │                          │ │
│   │                         └─────────┘                          │ │
│   └──────────────────────────────────────────────────────────────┘ │
│                                    ▲                                │
│                                    │ HTTP POST                      │
│                    ┌───────────────┼───────────────┐               │
│                    │               │               │               │
│   ┌────────────────┴──┐   ┌───────┴──────┐   ┌────┴────────────┐  │
│   │  SECONDARY NODE 1 │   │ SECONDARY 2  │   │  SECONDARY N    │  │
│   │                   │   │              │   │                 │  │
│   │  dnsdist          │   │  dnsdist     │   │  dnsdist        │  │
│   │     │             │   │     │        │   │     │           │  │
│   │  recursor         │   │  recursor    │   │  recursor       │  │
│   │     │             │   │     │        │   │     │           │  │
│   │  dnstap-processor │   │  dnstap-     │   │  dnstap-        │  │
│   │     │             │   │  processor   │   │  processor      │  │
│   │     ▼             │   │     │        │   │     │           │  │
│   │  sync-agent ──────┼───┼─────┼────────┼───┼──▶ sync-agent   │  │
│   │  (heartbeats,     │   │     ▼        │   │  (sends data    │  │
│   │   metrics,        │   │  sync-agent  │   │   to primary)   │  │
│   │   config sync)    │   │              │   │                 │  │
│   └───────────────────┘   └──────────────┘   └─────────────────┘  │
│
│   Data Flow:
│   • Queries: Client → dnsdist → recursor → internet
│   • Query Events: dnstap-processor → Primary /api/node-sync/ingest
│   • Node Metrics: sync-agent → Primary /api/node-sync/metrics
│   • Heartbeats: sync-agent → Primary /api/node-sync/heartbeat (60s)
│   • Config Sync: Primary → sync-agent → local recursor
│
└─────────────────────────────────────────────────────────────────────┘
```

For complete architecture details, see [Multi-Node Architecture](MULTI_NODE_ARCHITECTURE.md).

### Prerequisites

- Two or more servers (Linux recommended)
- Both servers must have network connectivity to each other
- Primary node must be running and accessible

### Step 1: Set Up the Primary Node

1. Deploy PowerBlockade normally (follow Steps 1-5 above)
2. Go to **Nodes** → **Add Node** in the admin UI
3. Enter a name for your secondary node (e.g., `bowlister`)
4. Click **Generate Deployment Package** - this creates a one-time setup command

### Step 2: Set Up the Secondary Node

On the secondary server:

```bash
# Clone the repository
git clone https://github.com/Zerostate-IO/PowerBlockade.git
cd PowerBlockade

# Generate base environment file
./scripts/init-env.sh
```

Now edit `.env` on the secondary to add the primary connection settings:

```bash
# Edit .env and add/update these values:
NODE_NAME=bowlister                    # Name you registered in step 1
PRIMARY_URL=http://PRIMARY_IP:8080    # URL of your primary node
PRIMARY_API_KEY=your-api-key-here     # From the deployment package in step 1
```

Then start with the sync-agent profile:

```bash
# Build and start (sync-agent profile enabled)
docker compose --profile sync-agent up -d --build
```

### Step 3: Verify Sync

1. Check the primary node's **Nodes** page - the secondary should appear as "Online"
2. On the secondary, check logs: `docker compose logs sync-agent`
3. You should see: `registered as <name>` and `heartbeat ok`

### What Syncs Automatically

Secondary nodes automatically sync from the primary:

- **Blocklists** - All blocklist subscriptions and entries
- **Forward Zones** - Split DNS configurations
- **Whitelist/Blacklist** - Manual overrides

### What is Sent to Primary

Secondary nodes send telemetry to the primary for centralized visibility:

- **Query logs** - DNS query events are POSTed to primary's `/api/node-sync/ingest`
- **Node metrics** - CPU, memory, query counts sent via sync-agent to `/api/node-sync/metrics`
- **Heartbeats** - Health status sent every 60 seconds (configurable)

> 📖 **See [Multi-Node Architecture](MULTI_NODE_ARCHITECTURE.md) for detailed data flow diagrams.**

### What Stays Local

Each node maintains its own:

- **DNS cache** - Per-node recursor cache for fast responses
- **Runtime state** - Container and process state

### Secondary Node Behavior

- **Normal operation**: Syncs config every 5 minutes, sends heartbeats every 60 seconds
- **Primary unreachable**: Continues operating independently with last-known config; buffers metrics and query events
- **Primary restored**: Automatically reconnects, sends buffered data, and syncs any missed changes

### Troubleshooting Multi-Node

**Secondary shows "Offline" on primary:**
```bash
# On secondary, check sync-agent is running
docker compose ps sync-agent
docker compose logs sync-agent
```

**"Permission denied" errors in sync-agent:**
```bash
# The init-permissions service should handle this automatically
# If you see permission errors, restart the stack:
docker compose --profile sync-agent down
docker compose --profile sync-agent up -d
```

**Secondary not syncing blocklists:**
- Verify `PRIMARY_URL` is correct and accessible from secondary
- Verify `PRIMARY_API_KEY` matches the one shown in the primary's Nodes page
- Check primary's API is accessible: `curl http://PRIMARY_IP:8080/health`

## Getting Help

- **In-app Help**: Click "Help" in the navigation for contextual documentation
- **GitHub Issues**: Report bugs or request features
- **DESIGN.md**: Technical architecture documentation in `docs/DESIGN.md`

## Next Steps

1. **Explore blocklists**: Try different lists to find the right balance of blocking vs. false positives
2. **Set up clients**: Go to Clients and assign friendly names to your devices
3. **Monitor for a week**: Check Blocked and Failures pages to tune your setup
4. **Consider multi-node**: For critical networks, set up a secondary node for redundancy

Welcome to PowerBlockade!
