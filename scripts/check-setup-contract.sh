#!/usr/bin/env bash
# PowerBlockade Setup Contract Drift Guard
#
# This script enforces the canonical setup contract across the codebase:
# - Primary is default (no --profile primary flag)
# - Secondary is explicit (--profile secondary is allowed)
# - No legacy manual secret generation patterns
# - All shell scripts must have valid syntax
#
# Usage:
#   ./scripts/check-setup-contract.sh              # Check canonical files
#   ./scripts/check-setup-contract.sh file1 file2  # Check specific files
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# ============================================
# Helper Functions
# ============================================

error() {
    echo -e "${RED}ERROR: $1${NC}" >&2
    ERRORS=$((ERRORS + 1))
}

warn() {
    echo -e "${YELLOW}WARNING: $1${NC}" >&2
    WARNINGS=$((WARNINGS + 1))
}

success() {
    echo -e "${GREEN}✓${NC} $1"
}

# ============================================
# Determine Files to Check
# ============================================

if [[ $# -gt 0 ]]; then
    # User provided specific files
    FILES_TO_CHECK=("$@")
    echo "Checking specified files: ${FILES_TO_CHECK[*]}"
else
    # Default to canonical files
    CANONICAL_DOCS=(
        "README.md"
        "QUICK_START.md"
        "docs/GETTING_STARTED.md"
        "docs/USING_PREBUILT_IMAGES.md"
        "deploy/README.md"
    )
    
    # Find all shell scripts in deploy/ and scripts/
    DEPLOY_SCRIPTS=()
    SCRIPTS=()
    
    if [[ -d "deploy" ]]; then
        while IFS= read -r -d '' file; do
            DEPLOY_SCRIPTS+=("$file")
        done < <(find deploy -name "*.sh" -print0 2>/dev/null)
    fi
    
    if [[ -d "scripts" ]]; then
        while IFS= read -r -d '' file; do
            SCRIPTS+=("$file")
        done < <(find scripts -name "*.sh" -print0 2>/dev/null)
    fi
    
    FILES_TO_CHECK=("${CANONICAL_DOCS[@]}" "${DEPLOY_SCRIPTS[@]}" "${SCRIPTS[@]}")
    echo "Checking canonical files and all shell scripts..."
fi

echo ""

# ============================================
# Check 1: Forbidden --profile primary Pattern
# ============================================

echo "=== Check 1: Forbidden --profile primary pattern ==="

FORBIDDEN_PROFILE_FILES=()
for file in "${FILES_TO_CHECK[@]}"; do
    # Skip this guard script itself
    if [[ "$file" == "scripts/check-setup-contract.sh" ]]; then
        continue
    fi
    if [[ -f "$file" ]]; then
        # Check for --profile primary (forbidden)
        # For shell scripts, skip comment lines
        # For markdown/docs, check all lines
        if [[ "$file" == *.sh ]]; then
            # In shell scripts, only check non-comment lines
            if grep -vE '^[[:space:]]*#' "$file" 2>/dev/null | grep -qE -- '--profile[[:space:]]+primary'; then
                FORBIDDEN_PROFILE_FILES+=("$file")
            fi
        else
            # In docs, check all lines
            if grep -qE -- '--profile[[:space:]]+primary' "$file" 2>/dev/null; then
                FORBIDDEN_PROFILE_FILES+=("$file")
            fi
        fi
    fi
done

if [[ ${#FORBIDDEN_PROFILE_FILES[@]} -gt 0 ]]; then
    error "Found forbidden '--profile primary' pattern in:"
    for file in "${FORBIDDEN_PROFILE_FILES[@]}"; do
        echo "  - $file"
        # Show the offending lines (skip comments in shell scripts)
        if [[ "$file" == *.sh ]]; then
            grep -vE '^[[:space:]]*#' "$file" 2>/dev/null | grep -n -- '--profile[[:space:]]+primary' | head -3 | while read -r line; do
                echo "    Line: $line"
            done
        else
            grep -n -- '--profile[[:space:]]+primary' "$file" | head -3 | while read -r line; do
                echo "    Line: $line"
            done
        fi
    done
    echo ""
    echo "  REMEDIATION: Primary is the default. Remove '--profile primary' flags."
    echo "  Use 'docker compose up -d' for primary (no profile flag)."
    echo "  Use 'docker compose --profile secondary up -d' for secondary nodes."
else
    success "No forbidden '--profile primary' patterns found"
fi

echo ""

# ============================================
# Check 2: Legacy Secret Generation Patterns
# ============================================

echo "=== Check 2: Legacy secret generation patterns ==="

# Only check deploy scripts for these patterns
LEGACY_PATTERNS=(
    # Pattern: generate_password function definition
    'generate_password\(\)'
    # Pattern: sed replacing ADMIN_PASSWORD in .env
    'sed[[:space:]]+.*-i.*ADMIN_PASSWORD'
    # Pattern: sed replacing POSTGRES_PASSWORD in .env
    'sed[[:space:]]+.*-i.*POSTGRES_PASSWORD'
)

LEGACY_PATTERN_FILES=()
for file in "${FILES_TO_CHECK[@]}"; do
    # Skip one-liner scripts - they are self-contained and cannot use init-env.sh
    if [[ "$file" == *-one-liner.sh ]]; then
        continue
    fi
    if [[ -f "$file" ]] && [[ "$file" == deploy/*.sh ]]; then
        for pattern in "${LEGACY_PATTERNS[@]}"; do
            if grep -qE "$pattern" "$file" 2>/dev/null; then
                LEGACY_PATTERN_FILES+=("$file")
                break  # Only count each file once
            fi
        done
    fi
done

if [[ ${#LEGACY_PATTERN_FILES[@]} -gt 0 ]]; then
    error "Found legacy secret generation patterns in deploy scripts:"
    for file in "${LEGACY_PATTERN_FILES[@]}"; do
        echo "  - $file"
        # Show which patterns matched
        for pattern in "${LEGACY_PATTERNS[@]}"; do
            if grep -qE "$pattern" "$file" 2>/dev/null; then
                echo "    Matched: $pattern"
            fi
        done
    done
    echo ""
    echo "  REMEDIATION: Use './scripts/init-env.sh --non-interactive' instead."
    echo "  Deploy scripts should delegate secret generation to init-env.sh."
else
    success "No legacy secret generation patterns found"
fi

echo ""

# ============================================
# Check 3: Shell Script Syntax
# ============================================

echo "=== Check 3: Shell script syntax validation ==="

SYNTAX_ERRORS=()
for file in "${FILES_TO_CHECK[@]}"; do
    if [[ -f "$file" ]] && [[ "$file" == *.sh ]]; then
        if ! bash -n "$file" 2>/dev/null; then
            SYNTAX_ERRORS+=("$file")
        fi
    fi
done

if [[ ${#SYNTAX_ERRORS[@]} -gt 0 ]]; then
    error "Shell scripts with syntax errors:"
    for file in "${SYNTAX_ERRORS[@]}"; do
        echo "  - $file"
        # Show the actual error
        bash -n "$file" 2>&1 | head -3 | while read -r line; do
            echo "    $line"
        done
    done
else
    success "All shell scripts have valid syntax"
fi

echo ""

# ============================================
# Check 4: Allowed --profile secondary Pattern
# ============================================

echo "=== Check 4: Verify --profile secondary is allowed ==="

# This is informational - we're confirming the pattern exists where expected
SECONDARY_PROFILE_COUNT=0
for file in "${FILES_TO_CHECK[@]}"; do
    if [[ -f "$file" ]]; then
        count=$(grep -c -- '--profile[[:space:]]\+secondary' "$file" 2>/dev/null || echo 0)
        count=$(echo "$count" | tr -d '[:space:]')
        if [[ "$count" -gt 0 ]]; then
            ((SECONDARY_PROFILE_COUNT += count))
        fi
    fi
done

if [[ $SECONDARY_PROFILE_COUNT -gt 0 ]]; then
    success "Found $SECONDARY_PROFILE_COUNT valid '--profile secondary' usages"
else
    echo "  No '--profile secondary' patterns found (this is OK for primary-only docs)"
fi

echo ""

# ============================================
# Summary
# ============================================

echo "==============================================="
echo "Summary"
echo "==============================================="
echo ""

if [[ $ERRORS -gt 0 ]]; then
    echo -e "${RED}FAILED: $ERRORS error(s) found${NC}"
    echo ""
    echo "The setup contract has been violated. Please fix the issues above."
    echo ""
    echo "Canonical setup contract:"
    echo "  1. Primary is default: docker compose -f docker-compose.ghcr.yml up -d"
    echo "  2. Secondary is explicit: docker compose -f docker-compose.ghcr.yml --profile secondary up -d"
    echo "  3. Secrets via init-env.sh: ./scripts/init-env.sh --non-interactive"
    echo "  4. No --profile primary flag (it's a no-op, remove it)"
    exit 1
else
    echo -e "${GREEN}PASSED: All setup contract checks passed${NC}"
    if [[ $WARNINGS -gt 0 ]]; then
        echo -e "  (${YELLOW}$WARNINGS warning(s)${NC})"
    fi
    exit 0
fi
