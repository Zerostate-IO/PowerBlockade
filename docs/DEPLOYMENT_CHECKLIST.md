# PowerBlockade Deployment Checklist

## Pre-Deployment Requirements

### 1. GHCR Package Visibility

**Before deploying, ensure Docker images are accessible:**

```bash
# Test from any machine
docker pull ghcr.io/zerostate-io/powerblockade-admin-ui:latest
```

**If you get "403 Forbidden":**

The packages are private. Choose one option:

#### Option A: Make Packages Public (Recommended for Open-Source)

1. Go to https://github.com/orgs/Zerostate-IO/packages
2. For each `powerblockade-*` package:
   - Click the package name
   - Click "Package settings" in the sidebar
   - Scroll to "Danger Zone" → "Change visibility"
   - Select "Public"

#### Option B: Authenticate Servers

On each server (celsate, bowlister):

1. Create a GitHub Personal Access Token:
   - Go to https://github.com/settings/tokens
   - Generate new token (classic)
   - Select `read:packages` scope
   - Copy the token

2. Login to GHCR:
   ```bash
   echo "YOUR_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
   ```

3. Verify:
   ```bash
   docker pull ghcr.io/zerostate-io/powerblockade-admin-ui:latest
   ```

---

## Primary Node Deployment (celsate)

### Server Requirements
- Ubuntu 22.04+ or similar Linux
- Docker & Docker Compose v2+
- Ports 53 (DNS) and 8080 (Admin UI) available
- Outbound HTTPS for blocklist updates

### Deployment Steps

1. **SSH to celsate:**
   ```bash
   ssh user@celsate
   ```

2. **Clone the repository and generate secrets:**
   ```bash
   git clone https://github.com/Zerostate-IO/PowerBlockade.git /opt/powerblockade
   cd /opt/powerblockade
   ./scripts/init-env.sh
   ```

3. **Start the stack with pre-built images:**
   ```bash
POWERBLOCKADE_VERSION=0.7.7 docker compose -f docker-compose.ghcr.yml up -d
   ```

4. **Save the admin password** printed by `init-env.sh`.

5. **Access Admin UI:**
   - URL: `http://CELSTATE_IP:8080`
   - Username: `admin`
   - Password: (from step 4)

### Verification Checklist

- [ ] Admin UI accessible at `http://celsate:8080`
- [ ] Can login with admin credentials
- [ ] DNS resolution works: `dig @celsate_ip google.com`
- [ ] Grafana dashboards load: `http://celsate:8080/grafana`
- [ ] Reloader sidecar running: `docker compose -f docker-compose.ghcr.yml ps recursor-reloader`

---

## Secondary Node Deployment (bowlister)

### Prerequisites
- Primary node (celsate) must be running
- Admin UI accessible from secondary node

### Deployment Steps

1. **On celsate (primary), generate node package:**
   - Go to Admin UI → Nodes → Add Node
   - Enter name: `bowlister`
   - Click "Generate Deployment Package"
   - Note the API key and primary URL

2. **SSH to bowlister:**
   ```bash
   ssh user@bowlister
   ```

3. **Clone the repository and configure for secondary:**
   ```bash
   git clone https://github.com/Zerostate-IO/PowerBlockade.git /opt/powerblockade
   cd /opt/powerblockade
   ./scripts/init-env.sh
   ```
   Set `NODE_NAME=bowlister`, `PRIMARY_URL=http://CELSATE_IP:8080`, and `PRIMARY_API_KEY` in `.env`.

4. **Start the secondary stack:**
   ```bash
POWERBLOCKADE_VERSION=0.7.7 docker compose -f docker-compose.ghcr.yml --profile secondary up -d
   ```

5. **Verify on celsate:**
   - Go to Admin UI → Nodes
   - `bowlister` should show as "Online"

### Verification Checklist

- [ ] DNS resolution works: `dig @bowlister_ip google.com`
- [ ] Node shows "Online" in primary's Admin UI
- [ ] Heartbeat received (check node details)
- [ ] Metrics syncing to primary

---

## Post-Deployment Configuration

### Blocklists
1. Go to Admin UI → Blocklists
2. Enable desired blocklists (AdGuard, StevenBlack, etc.)
3. Click "Apply Changes"

### DNS Configuration
1. Configure router/firewall DHCP to use PowerBlockade as DNS server
2. Point DNS to celsate (primary) IP for `:53`

### Monitoring
1. Check Grafana dashboards for query analytics
2. Set up alerts for critical metrics (optional)

---

## Upgrade Procedure

### Recommended: Upgrade Secondaries First

1. **Upgrade bowlister:**
   ```bash
   cd /opt/powerblockade
POWERBLOCKADE_VERSION=0.7.7 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.7 docker compose -f docker-compose.ghcr.yml --profile secondary up -d
   ```

2. **Verify bowlister is online** in primary's Admin UI

3. **Upgrade celsate:**
   ```bash
   cd /opt/powerblockade
POWERBLOCKADE_VERSION=0.7.7 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.7 docker compose -f docker-compose.ghcr.yml up -d
   ```

4. **Validate Recursor settings migration output:**
   ```bash
   docker compose -f docker-compose.ghcr.yml logs recursor | grep migrate-recursor-settings
   ls -la recursor/recursor.conf.template.bak.pre-migration
   ```

5. **Verify reloader sidecar started:**
   ```bash
   docker compose -f docker-compose.ghcr.yml ps recursor-reloader
   ```

### Rollback (if needed)

```bash
# Revert to previous version
POWERBLOCKADE_VERSION=v0.6.9 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=v0.6.9 docker compose -f docker-compose.ghcr.yml up -d
```

---

## Troubleshooting

### Container won't start
```bash
docker compose logs SERVICE_NAME
docker compose ps
```

### DNS not resolving
```bash
# Check dnsdist
docker compose logs dnsdist

# Check recursor
docker compose logs recursor

# Test directly
dig @localhost google.com
```

### DNS after host reboot
```bash
# Both services should recover to healthy
docker compose ps recursor dnsdist

# Verify the intended serving address answers
dig @HOST_LAN_IP google.com +short
```

- [ ] `recursor` shows `healthy`
- [ ] `dnsdist` shows `healthy`
- [ ] DNS answers on the configured LAN IP within 60 seconds of boot

### Secondary shows offline
```bash
# Check sync-agent
docker compose logs sync-agent

# Test connectivity
curl -I http://PRIMARY_IP:8080/health
```

### Database issues
```bash
# Check postgres
docker compose logs postgres

# Restore from backup
cat backups/backup_YYYYMMDD_HHMMSS.sql | docker compose exec -T postgres psql -U powerblockade
```

---

## Version History

| Version | Date | Notes |
|---------|------|-------|
| v0.7.6 | 2026-04-15 | Bugfix: reloader detection of bind-mounted forward-zones.conf changes |
| v0.7.5 | 2026-04-15 | Bugfix: secondary-package dnsdist addressing and static-IP/network contract |
| v0.7.4 | 2026-04-15 | Dedicated recursor-reloader sidecar with inotify file watching, atomic config writes |
| v0.7.3 | 2026-04-03 | Reboot recovery hardening for dnsdist/recursor startup and health checks |
| v0.7.0 | 2026-02-26 | PowerDNS stable-line upgrade and built-in recursor settings migration |
| v0.5.5 | 2026-02-26 | Documentation overhaul, GHCR deployment |
| v0.5.4 | 2026-02-26 | Pre-release testing |
| v0.4.1 | 2026-02-03 | UI improvements |
