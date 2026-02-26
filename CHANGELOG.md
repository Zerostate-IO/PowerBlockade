# Changelog

All notable changes to PowerBlockade are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

See [Release Policy](docs/RELEASE_POLICY.md) for version compatibility guarantees.

## [Unreleased]

### Added
- Built-in Recursor settings migration tooling (`recursor/migrate-settings.sh`) to rewrite legacy keys to current equivalents during upgrades.
- Upgrade flow hook in `scripts/pb` to run Recursor settings migration before service restart.

### Changed
- PowerDNS stack upgraded to stable lines: dnsdist 2.0 (`powerdns/dnsdist-20`) and Recursor 5.3 (`powerdns/pdns-recursor-53`).
- Recursor container startup now runs with `--enable-old-settings` while migration support is active.
- Default release references and user-facing version metadata moved to `v0.7.0` for the next feature release train.

### Fixed
- Secondary node package generator now emits a clean compose/env payload without duplicated template blocks.

### Operator Action Required

> ⚠️ **For upgrades to v0.7.0+**: review Recursor settings migration output on first restart.
> - Confirm `migrate-recursor-settings:` appears in Recursor logs during startup.
> - Keep `recursor/recursor.conf.template.bak.pre-migration` until post-upgrade validation is complete.
> - Upgrade secondaries first, then primary.

---

## [0.6.0] - 2025-02-25

> **Release Type**: Feature Release
> **Upgrade Safety**: See Operator Action Required below

### Added

- Multi-node architecture with centralized telemetry (query logs and metrics ship to primary)
- Sync-agent for secondary node configuration sync and health monitoring
- Event buffering on secondary nodes (bbolt store-and-forward for network partitions)
- Node metrics collection (uptime, query counts, cache stats)
- CI docs consistency checks workflow
- Upgrade validation checklist

### Changed

- **BREAKING**: Multi-node telemetry now ships to primary (query logs and metrics centralized)
  - Previous docs incorrectly stated these stayed local
  - See [Multi-Node Architecture](docs/MULTI_NODE_ARCHITECTURE.md) for data flow
- Heartbeat interval default changed from 30s to 60s (configurable via `HEARTBEAT_INTERVAL_SECONDS`)
- docker-compose.ghcr.yml now uses configurable subnet/IPs via env vars
- docker-compose.ghcr.yml now supports version pinning via `POWERBLOCKADE_VERSION`
- Release workflow sed pattern fixed for settings.py format

### Fixed

- Fixed "What Stays Local" section in GETTING_STARTED.md (telemetry ships to primary)
- Fixed heartbeat interval documentation (30s → 60s)
- Fixed release.yml sed pattern for settings.py (`pb_version: str =` format)
- Fixed double-publish risk by removing tag trigger from docker-build.yml

### Operator Action Required

> ⚠️ **For existing multi-node deployments**: This release changes how telemetry flows.
> - No action required for new deployments
> - Existing secondaries will automatically start sending metrics to primary
> - Query logs already shipped to primary; this is now accurately documented

### Upgrade Instructions

```bash
# Pull and restart
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d

# Or pin to this version
POWERBLOCKADE_VERSION=v0.6.0 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=v0.6.0 docker compose -f docker-compose.ghcr.yml up -d
```

---

## [0.5.8] - 2025-02-20

> **Release Type**: Patch Release
> **Upgrade Safety**: ✅ Safe upgrade, no manual steps required

### Fixed

- RPZ zone file generation improvements
- Cache warming reliability

### Upgrade Instructions

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

---

## Release Format Reference

Each release should follow this format:

```markdown
## [X.Y.Z] - YYYY-MM-DD

> **Release Type**: Patch | Feature | Major
> **Upgrade Safety**: Safe | See Operator Action Required

### Added
- New features

### Changed
- Changes to existing functionality
- Mark BREAKING changes explicitly

### Fixed
- Bug fixes

### Operator Action Required
(Only for feature/major releases with breaking changes)
> ⚠️ **Description of what operators need to do**

### Upgrade Instructions
```bash
# Standard upgrade commands
```
```

---

## Version Compatibility

| Version Range | Safe to Upgrade? | Notes |
|---------------|------------------|-------|
| 0.5.x → 0.5.y | ✅ Always | Patch releases are always safe |
| 0.5.x → 0.6.0 | ⚠️ Check docs | Feature release, may require config updates |
| 0.x.y → 1.0.0 | ⚠️ Read migration guide | Major release, breaking changes possible |

See [Release Policy](docs/RELEASE_POLICY.md) for complete details.
