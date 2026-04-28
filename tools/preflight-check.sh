#!/usr/bin/env bash
# Run before setup_gcp.sh and deploy_job.sh. Verifies auth + project + Docker.
# Never reads gcloud config — verifies project directly.
set -euo pipefail

PROJECT=img-dev-490919

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0

error()   { echo -e "${RED}✗ ERROR: $1${NC}"; ERRORS=$((ERRORS + 1)); }
warn()    { echo -e "${YELLOW}⚠ WARN:  $1${NC}"; }
success() { echo -e "${GREEN}✓ $1${NC}"; }

echo "=== Pre-flight check ==="

if gcloud auth list --filter="status=ACTIVE" --format="value(account)" 2>/dev/null | grep -q "@"; then
  ACCOUNT=$(gcloud auth list --filter="status=ACTIVE" --format="value(account)" 2>/dev/null | head -1)
  success "Authenticated as: ${ACCOUNT}"
else
  error "No active gcloud credentials. Run: gcloud auth login"
fi

if gcloud projects describe "${PROJECT}" --format="value(projectId)" &>/dev/null; then
  success "Project accessible: ${PROJECT}"
else
  error "Cannot access project ${PROJECT}. Check auth and project ID."
fi

if docker info &>/dev/null; then
  success "Docker daemon is running"
else
  error "Docker daemon is not running. Start Docker and retry."
fi

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  warn "Uncommitted changes in working tree — image will not reflect them"
fi

echo ""
if [ "${ERRORS}" -gt 0 ]; then
  echo -e "${RED}✗ ${ERRORS} error(s) found. Fix before proceeding.${NC}"
  exit 1
else
  echo -e "${GREEN}✓ All checks passed.${NC}"
fi
