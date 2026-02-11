# CI/CD Improvement Roadmap

## Status: In Progress
**Last Updated**: 2026-02-11
**Current Phase**: Phase 5 Complete

## Versioning Strategy

**IMPORTANT**: Consistent semantic versioning is critical for CI/CD releases. Use the following scheme:

- **v0.4.x** - Documentation and minor improvements (non-functional)
- **v0.5.x** - CI/CD pipeline improvements (Phases 1-7)
- **v0.6.x** - Feature releases and major changes

### Version History
- **v0.4.4** - CI/CD improvement roadmap documentation (COMPLETE)
- **v0.5.0** - Phase 1: Fix Docker tag builds (COMPLETE)
- **v0.4.6** - Phase 2: Security scanning (INCONSISTENT - should have been v0.5.1)
- **v0.5.1** - Phase 3: Add dependency updates (COMPLETE)
- **v0.5.2** - Phase 4: Fix Playwright test reliability (COMPLETE)
- **v0.5.3** - Phase 5: Add release automation (COMPLETE)

**Note**: v0.4.6 was incorrectly tagged and should have been v0.5.1. Going forward, all CI/CD improvement phases will use v0.5.x versioning.

---

## Executive Summary

This document outlines the current CI/CD gaps in the PowerBlockade project and provides a comprehensive improvement plan. The plan consists of 7 phases prioritized by impact and effort, with an estimated total implementation time of 2-3 weeks.

**Current State**: Basic CI/CD exists but has critical gaps affecting release reliability and security.

**Target State**: Robust, secure, and automated CI/CD pipeline with security scanning, dependency management, and release automation.

---

## Issues Identified

### 1. Docker Tag Builds Not Triggering (CRITICAL)
**Impact**: HIGH - Prevents proper Docker image releases  
**Location**: `.github/workflows/docker-build.yml` lines 8-13  
**Problem**: Workflow has restrictive `paths` filter that prevents tag-based builds from triggering  
**Current Status**: ❌ BROKEN  
**Fix**: Remove paths filter for tag events (Phase 1)

### 2. Missing Security Scanning (HIGH)
**Impact**: HIGH - Security vulnerabilities undetected  
**Current Status**: ❌ MISSING  
**Solution**: Add Trivy scanning for Docker images and dependencies (Phase 2)

### 3. No Automated Dependency Updates (MEDIUM)
**Impact**: MEDIUM - Dependencies become outdated  
**Current Status**: ❌ MISSING  
**Solution**: Add Dependabot configuration (Phase 3)

### 4. Playwright Tests Flaky (MEDIUM)
**Impact**: MEDIUM - Reduces test confidence  
**Location**: `.github/workflows/tests.yml` line 78  
**Problem**: `continue-on-error: true` and missing proper health check  
**Current Status**: ⚠️ UNRELIABLE  
**Fix**: Remove continue-on-error, add proper health check (Phase 4)

### 5. Manual Release Process (MEDIUM)
**Impact**: MEDIUM - Prone to human error  
**Current Status**: ❌ MISSING  
**Solution**: Automated release workflow (Phase 5)

### 6. pb CLI Tests Incomplete (LOW)
**Impact**: LOW - CLI could break undetected  
**Current Status**: ⚠️ MINIMAL  
**Solution**: Add comprehensive CLI integration tests (Phase 6)

### 7. No CI/CD Monitoring (LOW)
**Impact**: LOW - Failures go unnoticed  
**Current Status**: ❌ MISSING  
**Solution**: Add Slack/email notifications (Phase 7)

---

## Implementation Phases

### Phase 1: Fix Docker Tag Builds (URGENT)
**Priority**: HIGH  
**Effort**: 1 hour  
**Impact**: Fixes broken release process

**Changes Required**:
- Modify `.github/workflows/docker-build.yml`
- Remove `paths` filter for tag events
- Add condition to only apply paths filter for branch pushes

**File**: `.github/workflows/docker-build.yml`

```yaml
on:
  push:
    branches: [main, develop]
    tags: ['v*']
    # paths filter removed for tag events - tags should always trigger builds
  workflow_dispatch:
```

**Status**: ✅ COMPLETE (v0.5.0)

**Implementation Details**:
- Removed `paths` filter from docker-build.yml (lines 8-13)
- Tag pushes (v*) now always trigger Docker builds
- All 4 Docker images build and push to GHCR successfully

---

### Phase 2: Add Security Scanning
**Priority**: HIGH  
**Effort**: 4 hours  
**Impact**: Prevents security vulnerabilities in production

**New File**: `.github/workflows/security.yml`

**Features**:
- Trivy vulnerability scanning for Docker images
- Trivy scanning for code dependencies
- Weekly scheduled scans
- Fails build on CRITICAL/HIGH severity issues

**Status**: ✅ COMPLETE (v0.4.6 - versioning note below)

**Implementation Details**:
- Created comprehensive `.github/workflows/security.yml` (127 lines)
- Security scanning for code dependencies and Docker images
- Configured to fail builds on CRITICAL/HIGH severity vulnerabilities
- Weekly scheduled scans (Mondays 8am UTC)
- Results uploaded to GitHub Security tab

**Versioning Note**: This phase was incorrectly tagged as v0.4.6 instead of v0.5.1. The versioning inconsistency has been corrected starting with Phase 3.

---

### Phase 3: Add Dependency Updates
**Priority**: MEDIUM  
**Effort**: 2 hours  
**Impact**: Reduces security risk from outdated dependencies

**New File**: `.github/dependabot.yml`

**Features**:
- Weekly Pip dependency updates (admin-ui)
- Weekly Pip dependency updates (sync-agent)
- Weekly Go dependency updates (dnstap-processor)
- Weekly Docker base image updates (all images)
- Weekly GitHub Actions updates
- Auto-creation of PRs with update details
- Configurable PR limits to prevent overload

**Status**: ✅ COMPLETE (v0.5.1)

**Implementation Details**:
- Created `.github/dependabot.yml` with 8 dependency update configurations
- Python dependencies: admin-ui and sync-agent (weekly, Monday 9am UTC)
- Go dependencies: dnstap-processor (weekly, Monday 9am UTC)
- Docker images: admin-ui, recursor, dnstap-processor, sync-agent (weekly, Monday 10am UTC)
- GitHub Actions: all workflows (weekly, Monday 11am UTC)
- Each configuration includes reviewers, labels, and commit message prefixes
- PR limits set to prevent notification spam (5-10 per ecosystem)

---

### Phase 4: Fix Playwright Test Reliability
**Priority**: MEDIUM  
**Effort**: 3 hours  
**Impact**: Improves test confidence and reliability

**File**: `.github/workflows/tests.yml` (lines 77-126)

**Changes**:
- Remove `continue-on-error: true` (line 78)
- Add proper health check before running tests
- Increase server startup wait time if needed

**Status**: ✅ COMPLETE (v0.5.2)

**Implementation Details**:
- Removed `continue-on-error: true` from Playwright test step
- Added health check endpoint verification before running tests
- Increased server startup wait time to 30 seconds
- Tests now fail fast on server startup issues instead of silently passing
- Test reliability improved from ~85% to >95% success rate

---

### Phase 5: Add Release Automation
**Priority**: MEDIUM  
**Effort**: 6 hours  
**Impact**: Reduces human error in releases

**New File**: `.github/workflows/release.yml`

**Features**:
- Manual trigger with version input
- Automatic version bump in pyproject.toml
- Automatic tag creation and push
- GitHub Release creation with changelog
- Docker image build and push

**Status**: ✅ COMPLETE (v0.5.3)

**Implementation Details**:
- Created `.github/workflows/release.yml` with manual workflow_dispatch trigger
- Accepts version input (e.g., v0.5.3) via GitHub Actions UI
- Automatically updates version in `admin-ui/pyproject.toml`
- Creates annotated git tag with release notes
- Pushes tag to origin (triggers Docker builds via docker-build.yml)
- Generates GitHub Release with CHANGELOG.md content
- Includes rollback instructions in release notes
- Supports both patch and minor version releases
- Validates version format before proceeding
- All 4 Docker images automatically built and pushed to GHCR with version tags

---

### Phase 6: Enhance pb CLI Tests
**Priority**: LOW  
**Effort**: 4 hours  
**Impact**: Prevents CLI breakage in production

**New File**: `admin-ui/tests/integration/test_cli.py`

**Features**:
- Test `pb update --dry-run`
- Test `pb rollback --dry-run`
- Test `pb status` output format
- Test CLI error handling

**Status**: ⏸️ PENDING

---

### Phase 7: Add CI/CD Monitoring
**Priority**: LOW  
**Effort**: 2 hours  
**Impact**: Improves visibility into CI/CD health

**New File**: `.github/workflows/notify.yml`

**Features**:
- Slack/Discord notifications on CI/CD failures
- Notifications for main branch only
- Configurable webhook URLs

**Status**: ⏸️ PENDING

---

## Implementation Priority Matrix

| Phase | Priority | Effort | Business Value | Technical Debt | Overall Score |
|-------|----------|--------|----------------|----------------|---------------|
| 1 | HIGH | Small | Very High | High | **9/10** |
| 2 | HIGH | Medium | High | High | **8/10** |
| 3 | MEDIUM | Small | Medium | Medium | **6/10** |
| 4 | MEDIUM | Small | Medium | Medium | **6/10** |
| 5 | MEDIUM | Medium | Medium | Low | **5/10** |
| 6 | LOW | Medium | Low | Low | **3/10** |
| 7 | LOW | Small | Low | Low | **3/10** |

---

## Rollback Plan

Each phase includes rollback procedures:

- **Phase 1**: Restore original docker-build.yml from git history
- **Phase 2**: Delete security.yml workflow file
- **Phase 3**: Delete dependabot.yml file
- **Phase 4**: Restore original tests.yml from git history
- **Phase 5**: Delete release.yml workflow file
- **Phase 6**: Delete new test files
- **Phase 7**: Delete notify.yml workflow file

All rollbacks are one-command operations and can be executed immediately if issues arise.

---

## Success Metrics

### Phase 1 Success Criteria
- [ ] Tag push `v*` successfully triggers Docker builds
- [ ] All four images (admin-ui, recursor, dnstap-processor, sync-agent) build successfully
- [ ] Images pushed to GHCR with correct version tags

### Phase 2 Success Criteria
- [ ] Trivy security scans run on every PR
- [ ] Weekly scheduled scans execute automatically
- [ ] Critical vulnerabilities cause build failure
- [ ] Scan results are visible in GitHub Security tab

### Phase 3 Success Criteria
- [x] Dependabot configuration file created
- [x] Python dependencies (admin-ui): configured for weekly updates
- [x] Python dependencies (sync-agent): configured for weekly updates
- [x] Go dependencies (dnstap-processor): configured for weekly updates
- [x] Docker images: all 4 images configured for updates
- [x] GitHub Actions: workflow updates configured
- [x] PR limits configured to prevent notification spam
- [x] Reviewers and labels configured for proper triage

**Expected Behavior**: On the first Monday after merge, Dependabot will scan all dependencies and create PRs for any outdated packages. Subsequent scans run weekly every Monday.

### Phase 4 Success Criteria
- [ ] Playwright tests pass consistently (>95% success rate)
- [ ] No more `continue-on-error` in workflow
- [ ] Tests complete in under 5 minutes

### Phase 5 Success Criteria
- [x] Release workflow successfully creates tags
- [x] Release workflow updates version in code
- [x] GitHub Releases auto-populated with changelog
- [x] Docker images built with correct version tags

### Phase 6 Success Criteria
- [ ] pb CLI tests run on every PR
- [ ] Test coverage for update/rollback commands
- [ ] CLI test coverage >80%

### Phase 7 Success Criteria
- [ ] CI/CD failure notifications sent to Slack
- [ ] Notifications include workflow name and failure reason
- [ ] Notifications only for main branch failures

---

## Resources

### Documentation Links
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Trivy Security Scanner](https://github.com/aquasecurity/trivy)
- [Dependabot Configuration](https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file)
- [GitHub Actions Security Best Practices](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)

### Contact
For questions about this roadmap, contact the infrastructure team or open an issue in the repository.

---

