# PowerBlockade Quick Start

Get a DNS filtering server running in under 5 minutes.

## Requirements

- Docker & Docker Compose (v2+)
- A Linux server (Ubuntu 22.04+ recommended)
- Port 53 available (DNS)
- Port 8080 available (Admin UI)

## Step 1: Download

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
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/dnsdist/dnsdist.conf -o dnsdist/dnsdist.conf
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/prometheus/prometheus.yml -o prometheus/prometheus.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/grafana/provisioning/datasources/prometheus.yml -o grafana/provisioning/datasources/prometheus.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/grafana/provisioning/dashboards/dashboards.yml -o grafana/provisioning/dashboards/dashboards.yml
curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/grafana/dashboards/dns-overview.json -o grafana/dashboards/dns-overview.json
```

## Step 2: Configure

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

## Step 3: Start

```bash
docker compose up -d
```

Wait ~30 seconds for all services to start.

## Step 4: Access

- **Admin UI**: http://your-server:8080
- **Username**: `admin`
- **Password**: (shown in Step 2, or check with `grep ADMIN_PASSWORD .env`)

## Step 5: Point DNS

Configure your router or devices to use your server's IP as the DNS server.

---

## What's Running

| Service | Purpose |
|---------|---------|
| `dnsdist` | DNS frontend (port 53) |
| `recursor` | PowerDNS resolver |
| `admin-ui` | Web interface (port 8080) |
| `dnstap-processor` | Query logging |
| `postgres` | Database |
| `prometheus` | Metrics |
| `grafana` | Dashboards |

## Common Tasks

### View logs
```bash
docker compose logs -f admin-ui
```

### Stop everything
```bash
docker compose down
```

### Update to latest
```bash
docker compose pull
docker compose up -d
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
```

### DNS queries not working

```bash
# Test DNS resolution
dig @localhost google.com

# Check dnsdist logs
docker compose logs dnsdist
```

## Next Steps

1. **Add blocklists**: Go to Config > Blocklists in the Admin UI
2. **View query logs**: Go to Analytics > Query Logs
3. **Set up clients**: Go to Analytics > Clients to name your devices

For full documentation, see the [Getting Started Guide](https://github.com/Zerostate-IO/PowerBlockade/blob/main/docs/GETTING_STARTED.md).
