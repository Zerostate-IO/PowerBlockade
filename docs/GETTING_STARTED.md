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

# Generate environment file with random secrets
./scripts/init-env.sh
```

The `init-env.sh` script creates a `.env` file with secure random values for:
- `ADMIN_SECRET_KEY` - Session encryption key
- `ADMIN_PASSWORD` - Your admin login password (displayed after running)
- `PRIMARY_API_KEY` - Internal API authentication
- `RECURSOR_API_KEY` - Recursor management API key
- Database credentials

**Save the displayed admin password!** You'll need it to log in.

### (Optional) Review Configuration

```bash
# View generated config (don't share these values!)
cat .env
```

Key settings you might want to change in `.env`:
- `ADMIN_USERNAME` - Login username (default: `admin`)
- `ADMIN_PASSWORD` - Your password (regenerate if needed)

## Step 3: Start PowerBlockade

```bash
# Build and start all services
docker compose up -d --build
```

First startup takes 2-5 minutes to:
1. Build container images
2. Initialize the PostgreSQL database
3. Run database migrations
4. Start all services

Check that everything is running:

```bash
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

For high availability, you can run secondary nodes that sync from the primary:

### On the Secondary Node

```bash
# Clone and configure
git clone https://github.com/Zerostate-IO/PowerBlockade.git
cd PowerBlockade
./scripts/init-env.sh

# Start with sync-agent profile
docker compose --profile sync-agent up -d --build
```

### Register Secondary with Primary

1. On the **primary** node, go to **Nodes** → **Add Node**
2. Generate a deployment package
3. Follow the instructions to configure the secondary

Secondary nodes:
- Pull blocklists and forward zones from primary
- Send query logs back to primary for unified analytics
- Operate independently if primary is unreachable

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
