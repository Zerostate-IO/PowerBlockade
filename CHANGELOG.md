# Changelog

All notable changes to PowerBlockade are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

See [Release Policy](docs/RELEASE_POLICY.md) for version compatibility guarantees.

## [Unreleased]

## [0.7.5] - 2026-04-15

> **Release Type**: Patch Release (Bugfix)
> **Upgrade Safety**: Safe upgrade, no manual steps required
> **Supersedes**: v0.7.4 secondary-package generation was broken; use v0.7.5 for any secondary node deployments

### Fixed

- Generated secondary node packages now produce correct dnsdist backend addressing (was emitting invalid listen/bind configuration that prevented dnsdist startup on secondary nodes)
- Generated secondary node packages now use the correct static-IP and network contract so the secondary node's dnsdist binds to the intended LAN address instead of failing or binding to the wrong interface
- Node generator (`admin-ui/app/services/node_generator.py`) now matches the canonical compose health and dependency contract validated in v0.7.3

### Upgrade Instructions

Secondary nodes deployed from v0.7.4 generated packages must be re-deployed from a fresh v0.7.5 package.

```bash
POWERBLOCKADE_VERSION=0.7.5 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.5 docker compose -f docker-compose.ghcr.yml up -d
```

## [0.7.4] - 2026-04-15

> **Release Type**: Patch Release
> **Upgrade Safety**: Safe upgrade for primary nodes. Secondary node packages generated from v0.7.4 contain dnsdist addressing bugs; upgrade to v0.7.5 before deploying any secondary nodes.

### Added

- Dedicated `recursor-reloader` sidecar watches RPZ files and `forward-zones.conf` via inotify and runs `rec_control reload-lua-config` only when files actually change, eliminating unnecessary recursor load
- `powerblockade-recursor-reloader` image published to GHCR alongside existing component images

### Changed

- RPZ files on the primary are now written with `atomic_write()` (atomic replace via temp file) so the reloader sidecar sees clean inotify events instead of partial writes
- `forward-zones.conf` is now written with `safe_write()` (in-place overwrite preserving inode) so Docker file bind mounts stay consistent
- Generated secondary node packages now reference the official `powerblockade-recursor-reloader` GHCR image and use `docker-compose.ghcr.yml` as the compose file

### Fixed

- Replaced continuous 5-second `rec_control` polling with a dedicated file-watch sidecar that reloads the recursor only when config files change

### Upgrade Instructions

```bash
POWERBLOCKADE_VERSION=0.7.4 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=0.7.4 docker compose -f docker-compose.ghcr.yml up -d
```

## [0.7.3] - 2026-04-03

> **Release Type**: Patch Release
> **Upgrade Safety**: Safe upgrade, no manual steps required

### Changed

- dnsdist startup now waits for recursor readiness before accepting queries and fails fast if port 53 is not reachable inside the container
- dnsdist and recursor now use health-gated startup ordering so reboot recovery does not depend on container start order alone
- Generated secondary deployment packages now use the same health and dependency contract as the canonical compose files

### Fixed

- Post-reboot DNS outages where recursor was healthy but dnsdist never became reachable on the intended LAN IP
- dnsdist healthchecks on official images that do not ship with `dig`
- recursor healthchecks that treated lowercase `pong` responses as failures on live hosts

### Documentation

- Added reboot recovery verification guidance for LAN-IP testing, health checks, and dnsdist troubleshooting in deployment and getting-started docs
- Documented the live-validated distinction between VPN resolver success and PowerBlockade DNS reachability

### Validation

- Verified on `10.5.5.2` and `10.5.5.3` after a real power outage: `recursor` healthy, `dnsdist` healthy, and `dig @10.5.5.x google.com +short` succeeds locally and remotely

### Upgrade Instructions

```bash
POWERBLOCKADE_VERSION=v0.7.3 docker compose -f docker-compose.ghcr.yml pull
POWERBLOCKADE_VERSION=v0.7.3 docker compose -f docker-compose.ghcr.yml up -d
```

## [0.7.2] - 2026-03-03

> **Release Type**: Minor Feature Release
> **Upgrade Safety**: Safe upgrade, see Known Issues below

### Added

- Node lifecycle management with automatic state transitions (healthy → offline → quarantined)
- Quarantine-on-return for nodes offline >24 hours (configurable via `health_quarantine_threshold_minutes`)
- Metrics buffering for secondary nodes (7-day retention during primary outages)
- Version compatibility warnings in sync protocol (MINOR version skew = WARN, MAJOR = BLOCK)
- Scheduler job state tracking with PostgreSQL advisory locks

### Changed

- **BREAKING-ADJACENT**: Container startup now validates security settings
  - Installs with default/weak credentials will fail to start
  - Bypass available: `POWERBLOCKADE_ALLOW_INSECURE=true` (development only)
- Secondary node sync protocol now handles mixed-version deployments gracefully

### Fixed

- Advisory lock race conditions in scheduler jobs
- Secondary node compatibility with version skew during rolling upgrades

### Known Issues

- `pb rollback` does not automatically restore previous Docker image versions
  - **Workaround**: See [Manual Rollback Procedure](docs/UPGRADE.md#manual-rollback-procedure)

### Upgrade Instructions

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

---


## [0.7.1] - 2026-02-26

> **Release Type**: Patch Release
> **Upgrade Safety**: Safe upgrade, no manual steps required

### Added

- DNS53 benchmark script (`scripts/benchmark-dns53.sh`) with cold/warm/saturation test phases and configurable target QPS
- Rollback command pack documentation for staged deployments (`docs/ROLLBACK_COMMAND_PACKS.md`)
- Local gate runner script (`scripts/run-local-gates.sh`) for pre-deployment validation

### Changed

- DNS cache tuning configuration with explicit dnsdist `newPacketCache` parameters and recursor `refresh-on-ttl-perc` tuning
- Cache configuration includes inline rollback comments for quick restoration to defaults

### Validation

- Staged rollout completed: bowlister (secondary) validated for 30-minute soak, then celsate (primary) validated
- Rollback rehearsals passed on both nodes
- All local gate checks passed before promotion

### Upgrade Instructions

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

---

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
