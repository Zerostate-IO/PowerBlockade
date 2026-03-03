> **⚠️ DEPRECATED**: This changelog is no longer updated.
> For current release notes, see [CHANGELOG.md](../CHANGELOG.md) in the repository root.


# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Release automation workflow for GitHub Actions
- Comprehensive version management across all components
- CHANGELOG documentation

### Changed
- Admin UI version bumped to 0.4.0 for consistency
- Setup UX improvements: `--profile primary` removed (primary is now default)
- Environment setup streamlined: `./scripts/init-env.sh` replaces manual secret generation
- Added `--non-interactive` mode to init-env.sh for automation/CI
- Documentation reorganized with canonical setup path and cross-links
### Fixed
- Version alignment across admin-ui and main project

## [0.5.5] - 2026-02-26

### Fixed
- Uptime metrics now correctly collected (was looking for 'uptime_seconds' instead of 'uptime' in pdns_recursor metrics)
- Long-term Grafana dashboard rewritten to avoid problematic Grafana macros
- Added uptime panel to long-term dashboard

## [0.5.4] - 2026-02-26

### Fixed
- Grafana PostgreSQL datasource now correctly disables TimescaleDB (fixes long-term metrics dashboard)
- Sync-agent DNS resolution now uses configurable DNS_SERVER env var (fixes heartbeat blocking during precache)
- Prometheus retention time now configurable via PROMETHEUS_RETENTION_TIME env var

## [0.5.3] - 2026-02-11

### Added
- Phase 5: Release automation workflow (`.github/workflows/release.yml`)
- Automated version bumping and tagging
- Release notes generation
- Docker image publishing automation

### Changed
- Admin UI version updated to 0.4.0

## [0.5.2] - 2026-02-10

### Added
- Phase 4: Playwright test reliability improvements
- Health check integration for test stability

### Fixed
- Playwright test continue-on-error behavior
- Test flakiness issues

## [0.5.1] - 2026-02-09

### Added
- Phase 3: Automated dependency updates with Dependabot
- CI/CD roadmap documentation

## [0.5.0] - 2026-02-08

### Added
- Phase 2: Core DNS filtering infrastructure
- Multi-node support
- Query logging and analytics

### Fixed
- HTTP method for cache clearing (PUT instead of DELETE)
- Failures page filtering
- Top domains filter

## [0.4.0] - 2026-02-07

### Added
- Phase 1: Initial PowerBlockade release
- Admin UI with FastAPI
- PowerDNS Recursor integration
- dnsdist edge proxy
- Grafana dashboards
- Prometheus metrics

[Unreleased]: https://github.com/Zerostate-IO/PowerBlockade/compare/v0.5.5...HEAD
[0.5.5]: https://github.com/Zerostate-IO/PowerBlockade/compare/v0.5.4...v0.5.5
[0.5.4]: https://github.com/Zerostate-IO/PowerBlockade/compare/v0.5.3...v0.5.4
[0.5.3]: https://github.com/Zerostate-IO/PowerBlockade/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/Zerostate-IO/PowerBlockade/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/Zerostate-IO/PowerBlockade/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Zerostate-IO/PowerBlockade/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Zerostate-IO/PowerBlockade/releases/tag/v0.4.0
