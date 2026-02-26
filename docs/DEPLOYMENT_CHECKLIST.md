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

2. **Download deployment scripts:**
   ```bash
   mkdir -p /opt/powerblockade-deploy
   cd /opt/powerblockade-deploy
   curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary.sh -o deploy-primary.sh
   chmod +x deploy-primary.sh
   ```

3. **Run deployment:**
   ```bash
   ./deploy-primary.sh v0.7.0
   ```

4. **Save the admin password** from the output.

5. **Access Admin UI:**
   - URL: `http://CELSTATE_IP:8080`
   - Username: `admin`
   - Password: (from step 4)

### Verification Checklist

- [ ] Admin UI accessible at `http://celsate:8080`
- [ ] Can login with admin credentials
- [ ] DNS resolution works: `dig @celsate_ip google.com`
- [ ] Grafana dashboards load: `http://celsate:8080/grafana`

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

3. **Download deployment scripts:**
   ```bash
   mkdir -p /opt/powerblockade-deploy
   cd /opt/powerblockade-deploy
   curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-secondary.sh -o deploy-secondary.sh
   chmod +x deploy-secondary.sh
   ```

4. **Run deployment:**
   ```bash
   ./deploy-secondary.sh v0.7.0 http://CELSATE_IP:8080 API_KEY bowlister
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
   POWERBLOCKADE_VERSION=v0.7.0 docker compose pull
   POWERBLOCKADE_VERSION=v0.7.0 docker compose --profile sync-agent up -d
   ```

2. **Verify bowlister is online** in primary's Admin UI

3. **Upgrade celsate:**
   ```bash
   cd /opt/powerblockade
   POWERBLOCKADE_VERSION=v0.7.0 docker compose pull
   POWERBLOCKADE_VERSION=v0.7.0 docker compose up -d
   ```

4. **Validate Recursor settings migration output:**
   ```bash
   docker compose logs recursor | grep migrate-recursor-settings
   ls -la recursor/recursor.conf.template.bak.pre-migration
   ```

### Rollback (if needed)

```bash
# Revert to previous version
POWERBLOCKADE_VERSION=v0.6.9 docker compose pull
POWERBLOCKADE_VERSION=v0.6.9 docker compose up -d
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
| v0.7.0 | 2026-02-26 | PowerDNS stable-line upgrade and built-in recursor settings migration |
| v0.5.5 | 2026-02-26 | Documentation overhaul, GHCR deployment |
| v0.5.4 | 2026-02-26 | Pre-release testing |
| v0.4.1 | 2026-02-03 | UI improvements |
