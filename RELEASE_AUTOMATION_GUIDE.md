# PowerBlockade Release Automation Guide

Quick reference for updating versions and releasing new versions.

---

## ⚠️ MANDATORY PRE-RELEASE CHECKLIST

**DO NOT RELEASE without completing ALL items below. Missing any step = version mismatch in UI.**

- [ ] `admin-ui/pyproject.toml` - Update `version = "X.Y.Z"`
- [ ] `admin-ui/app/settings.py` - Update `pb_version: str = "X.Y.Z"`
- [ ] `admin-ui/Dockerfile` - Update `ARG PB_VERSION=X.Y.Z`
- [ ] `dnstap-processor/Dockerfile` - Update `ARG PB_VERSION=X.Y.Z` (2 occurrences!)
- [ ] `sync-agent/Dockerfile` - Update `ARG PB_VERSION=X.Y.Z`
- [ ] Verify: `grep -r "X.Y.Z" admin-ui/pyproject.toml admin-ui/app/settings.py admin-ui/Dockerfile dnstap-processor/Dockerfile sync-agent/Dockerfile`
- [ ] Build & deploy
- [ ] Confirm UI shows correct version in System Health page

---

### Step 1: Update Version Files (5 files)

```bash
# 1. Admin UI pyproject.toml
sed -i '' 's/version = ".*"/version = "X.Y.Z"/' admin-ui/pyproject.toml

# 2. Admin UI settings.py
sed -i '' 's/pb_version: str = ".*"/pb_version: str = "X.Y.Z"/' admin-ui/app/settings.py

# 3. Admin UI Dockerfile
sed -i '' 's/ARG PB_VERSION=.*/ARG PB_VERSION=X.Y.Z/' admin-ui/Dockerfile

# 4. dnstap-processor Dockerfile
sed -i '' 's/ARG PB_VERSION=.*/ARG PB_VERSION=X.Y.Z/' dnstap-processor/Dockerfile

# 5. sync-agent Dockerfile
sed -i '' 's/ARG PB_VERSION=.*/ARG PB_VERSION=X.Y.Z/' sync-agent/Dockerfile
```

### Step 2: Update Compose Files

```bash
# Update docker-compose.ghcr.yml to use versioned tags
sed -i '' 's/:latest/:vX.Y.Z/g' docker-compose.ghcr.yml

# Add build args to compose.yaml (if not already present)
# See section "Add Build Args to compose.yaml" below
```

### Step 3: Build Images

```bash
# Build all images with version injection
docker compose build \
  --build-arg PB_VERSION=X.Y.Z \
  --build-arg PB_GIT_SHA=$(git rev-parse --short HEAD) \
  --build-arg PB_BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
```

### Step 4: Tag and Push

```bash
# Tag images
docker tag powerblockade-admin-ui:latest ghcr.io/zerostate-io/powerblockade-admin-ui:vX.Y.Z
docker tag powerblockade-dnstap-processor:latest ghcr.io/zerostate-io/powerblockade-dnstap-processor:vX.Y.Z
docker tag powerblockade-sync-agent:latest ghcr.io/zerostate-io/powerblockade-sync-agent:vX.Y.Z

# Push to registry
docker push ghcr.io/zerostate-io/powerblockade-admin-ui:vX.Y.Z
docker push ghcr.io/zerostate-io/powerblockade-dnstap-processor:vX.Y.Z
docker push ghcr.io/zerostate-io/powerblockade-sync-agent:vX.Y.Z
```

### Step 5: Create Git Tag

```bash
git add -A
git commit -m "Release v${VERSION}"
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z
```

### Step 6: Create GitHub Release

```bash
gh release create vX.Y.Z \
  --title "PowerBlockade vX.Y.Z" \
  --notes "$(cat CHANGELOG.md | head -50)"
```

---

## Files to Update for Each Release

| File | Current | Change | Why |
|------|---------|--------|-----|
| `admin-ui/pyproject.toml` | `0.1.0` | → `X.Y.Z` | Package metadata |
| `admin-ui/app/settings.py` | `0.4.0` | → `X.Y.Z` | Runtime version (primary) |
| `admin-ui/Dockerfile` | `0.4.0` | → `X.Y.Z` | OCI image label |
| `dnstap-processor/Dockerfile` | `0.4.0` | → `X.Y.Z` | OCI image label |
| `sync-agent/Dockerfile` | `0.4.0` | → `X.Y.Z` | OCI image label |
| `docker-compose.ghcr.yml` | `:latest` | → `:vX.Y.Z` | Image pinning |
| `docs/CHANGELOG.md` | (update) | Add release notes | Release documentation |

---

## Detailed Instructions

### Add Build Args to compose.yaml

Edit `compose.yaml` and add `args:` to each service's build section:

```yaml
admin-ui:
  build:
    context: ./admin-ui
    args:
      PB_VERSION: "X.Y.Z"
      PB_GIT_SHA: "abc123def456"
      PB_BUILD_DATE: "2026-02-11T10:30:00Z"

dnstap-processor:
  build:
    context: ./dnstap-processor
    args:
      PB_VERSION: "X.Y.Z"
      PB_GIT_SHA: "abc123def456"
      PB_BUILD_DATE: "2026-02-11T10:30:00Z"

sync-agent:
  build:
    context: ./sync-agent
    args:
      PB_VERSION: "X.Y.Z"
```

### Update docker-compose.ghcr.yml

Change all `:latest` tags to `:vX.Y.Z`:

```yaml
admin-ui:
  image: ghcr.io/zerostate-io/powerblockade-admin-ui:vX.Y.Z

dnstap-processor:
  image: ghcr.io/zerostate-io/powerblockade-dnstap-processor:vX.Y.Z

sync-agent:
  image: ghcr.io/zerostate-io/powerblockade-sync-agent:vX.Y.Z
```

### Create CHANGELOG.md

```markdown
# Changelog

All notable changes to PowerBlockade are documented in this file.

## [X.Y.Z] - 2026-02-11

### Added
- Feature 1
- Feature 2

### Fixed
- Bug fix 1
- Bug fix 2

### Changed
- Change 1

### Deprecated
- Deprecated feature 1

## [X.Y.Z-1] - 2026-01-15

...
```

---

## Verification Checklist

After release, verify:

```bash
# 1. Check all version files match
grep -r "X.Y.Z" admin-ui/pyproject.toml admin-ui/app/settings.py admin-ui/Dockerfile dnstap-processor/Dockerfile sync-agent/Dockerfile

# 2. Check image labels
docker inspect ghcr.io/zerostate-io/powerblockade-admin-ui:vX.Y.Z | jq '.[0].Config.Labels."org.opencontainers.image.version"'

# 3. Check git tag
git tag | grep vX.Y.Z

# 4. Check GitHub release
gh release view vX.Y.Z
```

---

## Rollback Procedure

If something goes wrong:

```bash
# 1. Revert version files
git revert <commit-hash>

# 2. Delete git tag
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z

# 3. Delete GitHub release
gh release delete vX.Y.Z

# 4. Delete/unpush images (if needed)
docker rmi ghcr.io/zerostate-io/powerblockade-admin-ui:vX.Y.Z
```

---

## Automated Release Script (Recommended)

Create `/scripts/release.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "Usage: ./scripts/release.sh X.Y.Z"
    exit 1
fi

# Validate semver
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Version must be semver (X.Y.Z)"
    exit 1
fi

echo "Releasing PowerBlockade v$VERSION..."

# Update files
sed -i '' "s/version = \".*\"/version = \"$VERSION\"/" admin-ui/pyproject.toml
sed -i '' "s/pb_version: str = \".*\"/pb_version: str = \"$VERSION\"/" admin-ui/app/settings.py
sed -i '' "s/ARG PB_VERSION=.*/ARG PB_VERSION=$VERSION/" admin-ui/Dockerfile
sed -i '' "s/ARG PB_VERSION=.*/ARG PB_VERSION=$VERSION/" dnstap-processor/Dockerfile
sed -i '' "s/ARG PB_VERSION=.*/ARG PB_VERSION=$VERSION/" sync-agent/Dockerfile
sed -i '' "s/:latest/:v$VERSION/g" docker-compose.ghcr.yml

# Build
docker compose build \
  --build-arg PB_VERSION=$VERSION \
  --build-arg PB_GIT_SHA=$(git rev-parse --short HEAD) \
  --build-arg PB_BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Tag
docker tag powerblockade-admin-ui:latest ghcr.io/zerostate-io/powerblockade-admin-ui:v$VERSION
docker tag powerblockade-dnstap-processor:latest ghcr.io/zerostate-io/powerblockade-dnstap-processor:v$VERSION
docker tag powerblockade-sync-agent:latest ghcr.io/zerostate-io/powerblockade-sync-agent:v$VERSION

# Push
docker push ghcr.io/zerostate-io/powerblockade-admin-ui:v$VERSION
docker push ghcr.io/zerostate-io/powerblockade-dnstap-processor:v$VERSION
docker push ghcr.io/zerostate-io/powerblockade-sync-agent:v$VERSION

# Git
git add -A
git commit -m "Release v$VERSION"
git tag v$VERSION
git push origin main
git push origin v$VERSION

echo "✓ Release v$VERSION complete!"
```

Usage:
```bash
chmod +x scripts/release.sh
./scripts/release.sh 0.5.0
```

---

## Environment Variables for CI/CD

For GitHub Actions or other CI/CD:

```bash
export PB_VERSION=X.Y.Z
export PB_GIT_SHA=$(git rev-parse --short HEAD)
export PB_BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
export REGISTRY=ghcr.io
export REGISTRY_ORG=zerostate-io
```

---

## Known Issues & Workarounds

### Issue: pyproject.toml version mismatch

**Problem:** `pyproject.toml` has `0.1.0` but should be `0.4.0`

**Fix:** Update to match `settings.py`:
```bash
sed -i '' 's/version = "0.1.0"/version = "0.4.0"/' admin-ui/pyproject.toml
```

### Issue: compose.yaml doesn't inject version

**Problem:** Local builds don't pass `PB_VERSION` build arg

**Fix:** Add `args:` section to build config (see "Add Build Args to compose.yaml" above)

### Issue: docker-compose.ghcr.yml uses :latest

**Problem:** Always pulls latest, no version pinning

**Fix:** Update to use versioned tags (see "Update docker-compose.ghcr.yml" above)

---

## Testing Release

Before pushing to production:

```bash
# 1. Test local build
docker compose build

# 2. Start stack
docker compose up -d

# 3. Check version
curl http://localhost:8080/api/version | jq '.version'

# 4. Check image labels
docker inspect powerblockade-admin-ui | jq '.[0].Config.Labels."org.opencontainers.image.version"'

# 5. Run tests
./scripts/pb test

# 6. Cleanup
docker compose down
```

---

## References

- [VERSION_MANAGEMENT_AUDIT.md](./VERSION_MANAGEMENT_AUDIT.md) - Complete version audit
- [README.md](./README.md) - Project overview
- [GETTING_STARTED.md](./docs/GETTING_STARTED.md) - Setup guide
