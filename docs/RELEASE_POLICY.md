# Release Policy

> **Canonical Source**: This document defines the release compatibility policy for PowerBlockade. All releases and documentation, and and upgrade procedures must reference this policy.

---

## Version Numbering

PowerBlockade uses [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html):

### Version Format

- **MAJOR** (`X.0.0`): Breaking changes — may require manual operator intervention
- **MINOR** (`0.x.0`): New features, backward compatible
- **PATCH** (`1.0.x`): Bug fixes, backward compatible

### Examples

| Version | Type | Reason |
|---------|------|--------|
| `1.0.0` | PATCH | Bug fix, security patch, | `1.0.1` | PATCH | Performance improvement |
| `2.0.0` | MINOR | New blocklist source support | `2.1.0` | PATCH | Fix blocklist sync bug |
| `3.0.0` | MAJOR | Database schema migration required |

---

## Release Classes

### PATCH Release (0.0.X)

**Definition**: Bug fixes and security patches, and performance improvements

**Requirements**:
- No new environment variables required
- No configuration file format changes
- No database schema changes
- No API contract changes
- No changes to container startup behavior
- No manual operator intervention required

**Upgrade Safety**:
- **M guarantee**d safe**: `1.0.x` can be upgraded to `1.1.x` without any manual steps
- Rollback to `1.0.x` must straightforward: `docker compose pull && docker compose up -d`

**PASS/FAIL Criteria**:
- [ ] No new env keys in `.env.example`
- [ ] No configuration file format changes
- [ ] No database migrations
- [ ] No API contract changes
- [ ] Upgrade requires only `docker compose pull`
- [ ] Containers restart cleanly

---

### MINOR Release (0.X.0)

**Definition**: New features, enhancements

**Requirements**:
- New optional environment variables allowed
- New configuration options allowed
- Additive-only database schema changes
- New API endpoints (versioned)
- Optional manual operator intervention for new features

**Upgrade Safety**:
- **Not guaranteed safe**: `1.x.x` → `2.0.0` may require reviewing release notes
- Manual steps may be required for new features

**PASS/FAIL Criteria**:
- [ ] All PATCH criteria met- [ ] New env keys have `.env.example` with defaults
- [ ] New API endpoints are versioned (`/api/v2/...`)
- [ ] Additive-only DB migrations (no column drops/renames)

**Operator Actions Required** (if any):
```bash
# Check for new environment variables
grep -E "^NEW_VAR=" .env.example || echo "Set NEW_VAR in .env"

# Review new features in./scripts/pb check--help
```

---

### MAJOR Release (0.0.0)

**Definition**: Breaking changes requiring manual intervention

**Triggers**:
- Environment variable renamed or removed
- Configuration file format changes
- Database schema changes (column drops/renames)
- API contract changes (endpoint removal)
- Container startup behavior changes
- Network topology changes

**Requirements**:
- Explicit migration guide in release notes
- Clear deprecation timeline for removed features
- Rollback instructions

**Upgrade Safety**:
- **Not safe**: `1.x.x` → `2.0.0` requires careful review
- Full backup required before upgrade
- Test in staging environment

**PASS/FAIL Criteria**:
- [ ] **FAIL**: Release contains env renames without migration guide
- [ ] **FAIL**: Release removes API endpoint without deprecation notice
- [ ] **FAIL**: Release changes DB schema without migration path
- [ ] **FAIL**: Release requires manual config edits without explicit docs

**Operator Actions Required**:
```bash
# BEFORE upgrading:
# 1. Backup database
./scripts/pb backup

# 2. Review migration guide
# 3. Test in staging

# AFTER upgrading:
# 4. Run any migration scripts
docker compose exec admin-ui alembic upgrade head

# 5. Verify services
./scripts/pb status

# IF ISSUES:
# 6. Rollback
./scripts/pb rollback
```

---

## Release Notes Requirements

### PATCH Release

```markdown
## v1.0.X (YYYY-MM-DD)

### Fixed
- [Description of bug fixes]

### Security
- [CVE numbers if applicable]

### Changed
- [Internal changes, if any]
```

### MINOR Release

```markdown
## v1.X.0 (YYYY-MM-DD)

### Added
- [New features with usage examples]

### Changed
- [Internal changes]

### Operator Actions Required
- [ ] **None** if no new env/config changes

### Upgrade Impact
- [ ] **Low** — Standard `docker compose pull && up -d`
```

### MAJOR Release

```markdown
## vX.0.0 (YYYY-MM-DD)

### ⚠️ Breaking Changes

#### Environment Variables
- **RENAMED**: `OLD_VAR` → `NEW_VAR` (previously `OLD_VAR`, now use `NEW_VAR`)
- **REMOVED**: `DEPRECATED_VAR` (no longer used)

#### Configuration
- `config.yaml` format changed from YAML to TOML
- New required field: `required_field`

#### Database Migration
- Run `docker compose exec admin-ui alembic upgrade head`
- Estimated duration: X minutes
- Rollback: `docker compose exec admin-ui alembic downgrade -1`

#### API Changes
- **REMOVED**: `GET /api/v1/old-endpoint` (use `/api/v2/new-endpoint`)
- **CHANGED**: Response format changed

### Operator Actions Required
1. [ ] Backup database
2. [ ] Update environment variables
3. [ ] Run database migration
4. [ ] Verify services

### Rollback
1. [ ] Stop containers
2. [ ] Restore database from backup
3. [ ] Pin to previous version in docker-compose.ghcr.yml
4. [ ] Start containers
```

---

## Pre-Release Checklist

### All Releases
- [ ] Version number follows SemVer
- [ ] CHANGELOG.md updated
- [ ] All Dockerfiles have have correct `PB_VERSION`
- [ ] docker-compose.ghcr.yml tags
 updated (if not `:latest`)
- [ ] Tests pass
- [ ] Manual testing completed

### PATCH Releases
- [ ] No new env vars in `.env.example`
- [ ] No config format changes
- [ ] No DB schema changes
- [ ] Upgrade tested on clean install

### MINOR Releases
- [ ] New env vars
 documented in `.env.example`
- [ ] New features documented in README/GETTING_STARTED
- [ ] Backward compatibility verified

### MAJOR Releases
- [ ] Migration guide written
- [ ] Operator actions checklist in release notes
- [ ] Staging environment tested
- [ ] Rollback procedure documented
- [ ] Deprecation notice posted 30 days prior

---

## Compatibility Guarantee

### Within Same MAJOR Version
- **Guaranteed**: Patch and and minor releases work with same MAJOR version
- **Not guaranteed**: MAJOR version upgrades

### Upgrade Path
- Recommended: `1.x.x` → `1.x.y` → `1.y.z` → `2.0.0`
- Direct MAJOR jumps (skipping MINOR) require full review

### Deprecation Policy
- **Notice Period**: 30 days before removal
- **Migration Support**: Full migration guide in release notes
- **Removal**: MAJOR releases only
