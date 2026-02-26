# Compatibility Matrix

> **Canonical Source**: This document maps change types to allowed release classes.
 Reference: [RELEASE_POLICY.md](RELEASE_POLICY.md)

---

## Change Classification

| Change Type | Release Class | Backward Compatible | Operator Action Required |
|-------------|---------------|-------------------|------------------------|
| **Env Key Added** | MINOR | Yes | Add to `.env` if needed; defaults provided |
| **Env Key Renamed** | MAJOR | No | Update `.env` before upgrade |
| **Env Key Removed** | MAJOR | No | Remove from `.env`; verify no dependency |
| **Env Key Default Changed** | MINOR | Yes* | Review behavior; may need explicit setting |
| **Config File Added** | MINOR | Yes | Create new config; defaults provided |
| **Config Format Changed** | MAJOR | No | Migrate config file before upgrade |
| **Config Field Added** | MINOR | Yes | Add to config if needed |
| **Config Field Renamed** | MAJOR | No | Update config before upgrade |
| **Config Field Removed** | MAJOR | No | Remove from config |
| **DB Schema Add Table** | MINOR | Yes | None (automatic migration) |
| **DB Schema Add Column** | MINOR | Yes | None (automatic migration) |
| **DB Schema Rename Column** | MAJOR | No | Migration required; potential data loss |
| **DB Schema Drop Column** | MAJOR | No | Migration required; data loss possible |
| **DB Schema Change Type** | MAJOR | No | Migration required; may affect queries |
| **API Endpoint Added** | MINOR | Yes | None |
| **API Endpoint Removed** | MAJOR | No | Update clients before upgrade |
| **API Response Changed** | MINOR | Yes* | Update clients if using affected fields |
| **API Auth Changed** | MAJOR | No | Update auth configuration |
| **Compose Service Added** | MINOR | Yes | None |
| **Compose Service Removed** | MAJOR | No | Remove dependencies; update scripts |
| **Compose Env Changed** | MINOR | Yes | Review defaults |
| **Network Config Changed** | MINOR | Yes* | Review subnet config |
| **Docker Image Tag Changed** | PATCH | Yes | Pull new image |
| **PowerDNS Component Version Bump** | MINOR | Yes* | Verify recursor settings migration output on first restart |
| **Recursor Legacy-Key Migration Enabled** | MINOR | Yes* | Keep `.bak.pre-migration` backup until validation completes |
| **Health Check Changed** | MINOR | Yes | Update monitoring if needed |
| **Port Mapping Changed** | MAJOR | No | Update load balancer/firewall |

\* Requires review if behavior differs from previous default.

### PowerDNS Component Upgrade

- **Release Class**: MINOR
- **Backward Compatible**: Yes (with migration safeguards)
- **Operator Action**:
  - Verify `migrate-recursor-settings:` appears in Recursor logs after upgrade.
  - Confirm `recursor/recursor.conf.template.bak.pre-migration` exists during validation window.

---

## Rollback Notes

| Change Type | Rollback Complexity | Notes |
|-------------|--------------------|-------|
| Env Key Added | Low | Remove from `.env` |
| Env Key Renamed | Medium | Restore old name in `.env` |
| Env Key Removed | High | Restore old `.env` backup |
| DB Schema Add Column | Medium | `ALTER TABLE DROP COLUMN` |
| DB Schema Rename Column | High | Requires data migration; backup first |
| DB Schema Drop Column | **Critical** | **Data loss** — restore from backup |
| API Endpoint Removed | Medium | Revert API client code |
| Compose Service Removed | Low | Restore service definition |

---

## Current Environment Variables

### Required (Production)

| Variable | Default | Description | Change Impact |
|----------|---------|-------------|----------------|
| `ADMIN_SECRET_KEY` | *(none)* | Session encryption key | Renaming: MAJOR |
| `ADMIN_PASSWORD` | *(none)* | Admin password | Removal: MAJOR |
| `POSTGRES_PASSWORD` | *(none)* | Database password | Renaming: MAJOR |
| `RECURSOR_API_KEY` | *(none)* | Recursor API key | Renaming: MAJOR |
| `GRAFANA_ADMIN_PASSWORD` | *(none)* | Grafana password | Renaming: MAJOR |

### Network Configuration

| Variable | Default | Description | Change Impact |
|----------|---------|-------------|----------------|
| `DOCKER_SUBNET` | `172.30.0.0/24` | Docker network subnet | Default change: MINOR |
| `RECURSOR_IP` | `172.30.0.10` | Recursor container IP | Default change: MINOR |
| `DNSTAP_PROCESSOR_IP` | `172.30.0.20` | dnstap-processor IP | Default change: MINOR |
| `DNSDIST_LISTEN_ADDRESS` | `0.0.0.0` | DNS bind address | Default change: MINOR |

### Optional

| Variable | Default | Description | Change Impact |
|----------|---------|-------------|----------------|
| `NODE_NAME` | `primary` | Node identifier | Renaming: MINOR |
| `TIMEZONE` | `America/Los_Angeles` | Timezone | Default change: MINOR |
| `PROMETHEUS_RETENTION_TIME` | `30d` | Metrics retention | Default change: MINOR |
| `HEARTBEAT_INTERVAL_SECONDS` | `60` | Heartbeat frequency | Default change: MINOR |
| `CONFIG_SYNC_INTERVAL_SECONDS` | `300` | Config sync frequency | Default change: MINOR |

### Multi-Node (Secondary Only)

| Variable | Default | Description | Change Impact |
|----------|---------|-------------|----------------|
| `PRIMARY_API_KEY` | *(none)* | Auth key for primary | Renaming: MAJOR |
| `PRIMARY_URL` | `http://admin-ui:8080` | Primary admin-ui URL | Default change: MINOR |

---

## Database Schema Changes

### Adding New Table

- **Release Class**: MINOR
- **Backward Compatible**: Yes
- **Migration**: Automatic via Alembic
- **Rollback**: `alembic downgrade -1`

### Adding New Column
- **Release Class**: MINOR
- **Backward Compatible**: Yes
- **Migration**: Automatic via Alembic
- **Rollback**: `alembic downgrade -1`

### Renaming Column
- **Release Class**: MAJOR
- **Backward Compatible**: No
- **Migration**: Manual Alembic migration required
- **Data Risk**: Low (copy data before rename)
- **Rollback**: Complex — restore from backup

### Dropping Column
- **Release Class**: MAJOR
- **Backward Compatible**: No
- **Migration**: Manual Alembic migration required
- **Data Risk**: **HIGH** — data loss permanent
- **Rollback**: **IMPOSSIBLE** without backup

---

## API Versioning

PowerBlockade uses URL-based API versioning:

| Version | Path | Status |
|---------|------|--------|
| v1 | `/api/v1/...` | Current |
| Node Sync | `/api/node-sync/...` | Current |

### Adding New Endpoint
- **Release Class**: MINOR
- **Backward Compatible**: Yes

### Removing Endpoint
- **Release Class**: MAJOR
- **Notice Required**: 30 days deprecation notice
- **Migration**: Document replacement endpoint

### Changing Response Format
- **Release Class**: MINOR (additive) or MAJOR (breaking)
- **Backward Compatible**: Only if new fields are added

---

## Compose File Changes

### docker-compose.ghcr.yml

| Change | Release Class | Notes |
|--------|---------------|-------|
| Add service | MINOR | New optional service |
| Remove service | MAJOR | Breaking for dependent setups |
| Change image tag | PATCH | Pull new image |
| Add env var | MINOR | Document in `.env.example` |
| Remove env var | MAJOR | Breaking change |
| Change network | MINOR | May require network reconfiguration |

### compose.yaml

| Change | Release Class | Notes |
|--------|---------------|-------|
| Any change | PATCH/MINOR | Development compose file |
| Build context change | MINOR | Affects local builds only |

---

## Release Workflow Alignment

| Change Type | Workflow Update Required | Validation |
|-------------|------------------------|------------|
| Version bump | Update `release.yml` sed patterns | Verify all files updated |
| New env var | Add to `.env.example` | Check init-env.sh generates it |
| Schema migration | Add to Alembic | Test upgrade path |
| API change | Update docs | Test client compatibility |
