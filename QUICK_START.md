# PowerBlockade Quick Start

Get a DNS filtering server running in under 5 minutes using **pre-built Docker images**.

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
- **Port 53** available (DNS)
- **Port 8080** available (Admin UI)

## Step 0: GHCR Authentication (If Images Are Private)

If the Docker images are stored in a **private** GitHub Container Registry, you must authenticate first.

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

## Step 1: Create Directory and Download Files

```bash
# Create directory and download required files
mkdir -p powerblockade && cd powerblockade

# Download compose file and example env
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/docker-compose.ghcr.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/.env.example -o .env

# Download required config files
mkdir -p recursor/rpz dnsdist grafana/provisioning/datasources grafana/provisioning/dashboards grafana/dashboards prometheus
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/recursor/recursor.conf.template -o recursor/recursor.conf.template
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/recursor/rpz.lua -o recursor/rpz.lua
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/recursor/forward-zones.conf -o recursor/forward-zones.conf
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/dnsdist/dnsdist.conf.template -o dnsdist/dnsdist.conf.template
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/dnsdist/docker-entrypoint.sh -o dnsdist/docker-entrypoint.sh
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/prometheus/prometheus.yml -o prometheus/prometheus.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/grafana/provisioning/datasources/prometheus.yml -o grafana/provisioning/datasources/prometheus.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/grafana/provisioning/dashboards/dashboards.yml -o grafana/provisioning/dashboards/dashboards.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/grafana/dashboards/dns-overview.json -o grafana/dashboards/dns-overview.json
```

## Step 2: Configure Secrets

Generate secure passwords:

```bash
# Generate random passwords and update .env
generate_password() { openssl rand -base64 24 | tr -d '\n' | tr '+/' '-_'; }

sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$(generate_password)/" .env
sed -i "s/^ADMIN_SECRET_KEY=.*/ADMIN_SECRET_KEY=$(generate_password)$(generate_password)/" .env
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(generate_password)/" .env
sed -i "s/^RECURSOR_API_KEY=.*/RECURSOR_API_KEY=$(generate_password)/" .env
sed -i "s/^PRIMARY_API_KEY=.*/PRIMARY_API_KEY=$(generate_password)/" .env
sed -i "s/^GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$(generate_password)/" .env

# Fix DATABASE_URL to use the generated postgres password
PGPASS=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2)
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://powerblockade:${PGPASS}@postgres:5432/powerblockade|" .env

echo "Passwords generated! Your admin password:"
grep '^ADMIN_PASSWORD=' .env
```

> ⚠️ **Save your admin password!** You'll need it to log in.

## Step 3: Start PowerBlockade

```bash
docker compose up -d
```

Wait ~30 seconds for all services to start. Check status:

```bash
docker compose ps
```

All containers should show `Up` or `healthy`.

### Version Pinning (Recommended for Production)

To pin to a specific version instead of `latest`:

```bash
# Pin to a specific release
POWERBLOCKADE_VERSION=v0.7.0 docker compose up -d
```

## Step 4: Access the Admin UI

- **Admin UI**: http://your-server:8080
- **Username**: `admin`
- **Password**: (shown in Step 2, or check with `grep ADMIN_PASSWORD .env`)

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
docker compose logs -f admin-ui
docker compose logs -f dnsdist
docker compose logs -f recursor
```

### Stop everything

```bash
docker compose down
```

### Update to latest version

```bash
docker compose pull
docker compose up -d
```

### Update to a specific version

```bash
POWERBLOCKADE_VERSION=v0.7.0 docker compose pull
POWERBLOCKADE_VERSION=v0.7.0 docker compose up -d
```

### Check status

```bash
docker compose ps
```

## Troubleshooting

### Port 53 already in use

Another service is using DNS. Common culprits:

```bash
# Check what's using port 53
sudo lsof -i :53

# On Ubuntu, disable systemd-resolved
sudo systemctl disable --now systemd-resolved
```

### Can't connect to Admin UI

```bash
# Check if admin-ui is running
docker compose ps admin-ui

# Check logs for errors
docker compose logs admin-ui

# Check firewall allows port 8080
sudo ufw allow 8080/tcp
```

### DNS queries not working

```bash
# Test DNS resolution locally
dig @localhost google.com

# Check dnsdist logs
docker compose logs dnsdist

# Check recursor logs
docker compose logs recursor
```

### Docker network conflicts

If the default subnet (`172.30.0.0/24`) conflicts with your network:

```bash
# Check for conflicts
ip route | grep 172.30

# Edit .env to use a different subnet
echo "DOCKER_SUBNET=172.31.0.0/24" >> .env
echo "RECURSOR_IP=172.31.0.10" >> .env
echo "DNSTAP_PROCESSOR_IP=172.31.0.20" >> .env

# Restart
docker compose down
docker compose up -d
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
