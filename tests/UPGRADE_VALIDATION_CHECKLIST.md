# Upgrade Validation Checklist

This checklist should be run after every release to ensure upgrades work correctly.

## Pre-Upgrade Checks

- [ ] Backup database: `docker compose exec postgres pg_dump -U powerblockade powerblockade > backup.sql`
- [ ] Note current version: `docker compose exec admin-ui cat /app/version.txt`
- [ ] Verify all containers healthy: `docker compose ps`
- [ ] Check secondary nodes are online (multi-node): Admin UI → Nodes

## Upgrade Steps

- [ ] Pull new images: `docker compose -f docker-compose.ghcr.yml pull`
- [ ] Restart services: `docker compose -f docker-compose.ghcr.yml up -d`

## Post-Upgrade Validation

### Core Functionality

- [ ] All containers running: `docker compose ps` shows all `Up`
- [ ] Admin UI accessible: Open http://server:8080
- [ ] Login works: Use admin credentials
- [ ] Version updated: System Health shows new version

### DNS Functionality

- [ ] DNS resolution works: `dig @server google.com` returns A record
- [ ] Blocking works: `dig @server ad.doubleclick.net` returns NXDOMAIN (if blocklists active)
- [ ] Query logs appear: Admin UI → Logs shows queries

### Database

- [ ] Database migrations applied: No errors in admin-ui logs
- [ ] Data preserved: Blocklists, clients, settings still present
- [ ] Query history intact: Recent queries visible in logs

### Multi-Node (if applicable)

- [ ] Secondaries show "Online" on primary: Admin UI → Nodes
- [ ] Sync-agent running: `docker compose logs sync-agent` shows heartbeats
- [ ] Config sync working: Blocklist changes propagate to secondaries

### Grafana

- [ ] Grafana accessible: Admin UI → System Health → Grafana
- [ ] Dashboards load: DNS Overview dashboard shows data
- [ ] Prometheus metrics: Data visible in graphs

## Rollback Test (Optional)

If testing rollback capability:

- [ ] Rollback command works: `./scripts/pb rollback` (if using pb CLI)
- [ ] Or manual rollback: Set `POWERBLOCKADE_VERSION=previous-version` and restart
- [ ] Database restored: Data intact after rollback

## Performance Checks

- [ ] Cache hit rate normal: System Health → Cache Hit Rate > 50%
- [ ] Query latency acceptable: `dig` responses within 100ms for cached queries
- [ ] No memory leaks: `docker stats` shows stable memory usage

## Error Checks

- [ ] No errors in admin-ui logs: `docker compose logs admin-ui | grep -i error`
- [ ] No errors in recursor logs: `docker compose logs recursor | grep -i error`
- [ ] No errors in dnsdist logs: `docker compose logs dnsdist | grep -i error`
- [ ] No permission errors: `docker compose logs | grep -i "permission denied"`

## Automated Test Script

For quick validation, run this script after upgrade:

```bash
#!/bin/bash
# upgrade-validation.sh

set -e

echo "=== Upgrade Validation ==="

# Check containers
echo "Checking containers..."
CONTAINERS=$(docker compose ps --format json | jq -r '.[] | select(.State != "running") | .Name')
if [[ -n "$CONTAINERS" ]]; then
    echo "❌ Containers not running: $CONTAINERS"
    exit 1
fi
echo "✅ All containers running"

# Check DNS
echo "Checking DNS..."
if ! dig @localhost +short google.com > /dev/null 2>&1; then
    echo "❌ DNS resolution failed"
    exit 1
fi
echo "✅ DNS resolution works"

# Check Admin UI
echo "Checking Admin UI..."
if ! curl -sf http://localhost:8080/health > /dev/null; then
    echo "❌ Admin UI health check failed"
    exit 1
fi
echo "✅ Admin UI healthy"

# Check for errors in logs
echo "Checking for errors..."
ERRORS=$(docker compose logs --tail=100 2>&1 | grep -ci "error" || echo "0")
if [[ "$ERRORS" -gt 5 ]]; then
    echo "⚠️  Found $ERRORS error entries in logs (may be normal)"
else
    echo "✅ No significant errors in logs"
fi

echo ""
echo "=== Validation Complete ==="
```

## Release-Specific Checks

Check CHANGELOG.md for release-specific validation steps:

- [ ] New features work as documented
- [ ] Breaking changes handled (if feature release)
- [ ] New environment variables added (if required)

## Sign-Off

- Validator: _______________
- Date: _______________
- Version: _______________
- Issues found: _______________