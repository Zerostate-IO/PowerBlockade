# Documentation Truth Map

> **Purpose**: Classifies each user-facing doc in PowerBlockade by ownership, drift risk, and canonical status.
> **Last Updated**: 2025-02-25

## Document Classification

| File | Type | Status | Owner | Notes |
|------|------|--------|-------|-------|
| README.md | Entry | Primary | docs/ | Main repo entry point |
| QUICK_START.md | Guide | Derived | docs/GETTING_STARTED.md | Prebuilt-image-first quick start |
| docs/GETTING_STARTED.md | Guide | Canonical | docs/MULTI_NODE_ARCHITECTURE.md | Full walkthrough |
| docs/MULTI_NODE_ARCHITECTURE.md | Architecture | Canonical | Code | Multi-node data flow reference |
| docs/UPGRADE.md | Guide | Canonical | docs/RELEASE_POLICY.md | Upgrade instructions |
| docs/RELEASE_POLICY.md | Policy | Canonical | Code | SemVer compatibility guarantees |
| docs/COMPATIBILITY_MATRIX.md | Reference | Canonical | docs/RELEASE_POLICY.md | Change type → release class mapping |
| docs/DESIGN.md | Architecture | Canonical | Code | Technical architecture |
| docs/USING_PREBUILT_IMAGES.md | Guide | Derived | QUICK_START.md | GHCR usage details |
| CHANGELOG.md | History | Canonical | Code | Release history with operator impact |
| .env.example | Config | Canonical | scripts/init-env.sh | Environment variable contract |
| docker-compose.ghcr.yml | Config | Canonical | compose.yaml | Prebuilt image deployment |
| compose.yaml | Config | Canonical | Code | Local build deployment |
| scripts/pb | Operations | Canonical | docs/UPGRADE.md | CLI update tool |
| scripts/init-env.sh | Operations | Canonical | .env.example | Environment seeding |

## In-App Help Templates

| Template | Topic | Canonical Source | Last Verified |
|----------|-------|------------------|---------------|
| help/multi-node.html | Multi-node | docs/MULTI_NODE_ARCHITECTURE.md | 2025-02-25 |
| help/system-updates.html | Upgrades | docs/UPGRADE.md | 2025-02-25 |
| help/dns-blocking.html | RPZ | docs/DESIGN.md | Stable |
| help/forward-zones.html | Split DNS | docs/DESIGN.md | Stable |
| help/clients.html | Clients | - | Stable |
| help/precache.html | Caching | - | Stable |
| help/audit.html | Config audit | - | Stable |

## Resolved Contradictions

The following contradictions were identified and resolved:

| Topic | Previous State | Resolution | Date |
|-------|----------------|------------|------|
| Heartbeat interval | GETTING_STARTED said 60s, multi-node.html said 30s | Both now say 60s (matches code default) | 2025-02-25 |
| Query logs location | GETTING_STARTED said "stay local" | Fixed: logs ship to primary via dnstap-processor | 2025-02-25 |
| Metrics location | GETTING_STARTED said "stay local" | Fixed: metrics ship to primary via sync-agent | 2025-02-25 |
| docker-compose.ghcr.yml | Hardcoded org, subnet, :latest | Now uses env vars for all | 2025-02-25 |
| .env.example | Missing network keys | Added DOCKER_SUBNET, RECURSOR_IP, DNSTAP_PROCESSOR_IP | 2025-02-25 |
| Release workflow | sed pattern mismatched settings.py | Fixed to match `pb_version: str =` format | 2025-02-25 |
| Double-publish risk | Both release.yml and docker-build.yml triggered on tags | Removed tag trigger from docker-build.yml | 2025-02-25 |

## Drift Risk Assessment

### Low Risk
- **QUICK_START.md** - References GETTING_STARTED.md, changes together
- **docs/UPGRADE.md** - New canonical doc, clear owner

### Medium Risk
- **In-app help templates** - Must be updated when canonical docs change
- **docker-compose.ghcr.yml** - Should track compose.yaml feature parity

### High Risk
- **Multi-node documentation** - Spans multiple files; must keep consistent
- **Upgrade documentation** - Must be tested before each release

## CI Protection

The `docs-check.yml` workflow validates:
1. Internal doc links are valid
2. .env.example contains all required keys
3. Heartbeat interval is consistent (60s)
4. docker-compose.ghcr.yml has all required services

## Update Protocol

When changing multi-node behavior:
1. Update `docs/MULTI_NODE_ARCHITECTURE.md` first
2. Update `docs/GETTING_STARTED.md` multi-node section
3. Update `admin-ui/app/templates/help/multi-node.html`
4. Run CI docs-check workflow

When changing upgrade process:
1. Update `docs/RELEASE_POLICY.md` if compatibility affected
2. Update `docs/UPGRADE.md` with new steps
3. Update `admin-ui/app/templates/help/system-updates.html`
4. Update `CHANGELOG.md` with operator impact