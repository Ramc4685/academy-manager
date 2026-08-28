#!/usr/bin/env bash
# classify-changes.sh — change-tier classifier shared by the pre-push hook
# (scripts/dev/pre-push-checks.sh) and its tests
# (scripts/dev/pre-push-checks.test.sh, run in CI by the Hook Classifier
# Tests job). Pure classification: no git, no side effects.
#
# classify_changes "<newline-separated changed paths>" [--full]
#
# Sets (in the caller's shell):
#   DOCS_ONLY        true when every changed file is docs/markdown/templates
#   BACKEND_CHANGED  any file under backend/
#   FRONTEND_CHANGED any file under frontend/
#   HIGH_RISK        any file matching CLASSIFY_HIGH_RISK_RE below
#   RUN_E2E          any file under frontend/e2e/, or --full
#   BROAD            --full, high-risk, or mixed backend+frontend

# Paths where a mistake is expensive enough to always warrant the broad tier:
# auth/tenancy/billing/payments, migrations, CI, deployment, shared infra.
CLASSIFY_HIGH_RISK_RE='^\.github/workflows/|^scripts/|^docker|compose.*\.ya?ml$|^fly\.toml|requirements.*\.txt$|pnpm-lock\.yaml$|package\.json$|auth|tenan|billing|stripe|payment|invoice|checkout|webhook|migrat|middleware|composition'

classify_changes() {
  local changed="${1-}" full="${2:-}"
  DOCS_ONLY=true
  BACKEND_CHANGED=false
  FRONTEND_CHANGED=false
  HIGH_RISK=false
  RUN_E2E=false
  BROAD=false

  local f
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    case "$f" in
      docs/*|*.md|.github/ISSUE_TEMPLATE/*|LICENSE*) ;;
      *) DOCS_ONLY=false ;;
    esac
    case "$f" in
      backend/*)  BACKEND_CHANGED=true ;;
      frontend/*) FRONTEND_CHANGED=true ;;
    esac
    case "$f" in
      frontend/e2e/*) RUN_E2E=true ;;
    esac
    if printf '%s' "$f" | grep -qiE "$CLASSIFY_HIGH_RISK_RE"; then
      HIGH_RISK=true
    fi
  done <<< "${changed}"

  if [ "$full" = "--full" ]; then
    RUN_E2E=true
  fi
  if [ "$full" = "--full" ] || [ "$HIGH_RISK" = true ] || { [ "$BACKEND_CHANGED" = true ] && [ "$FRONTEND_CHANGED" = true ]; }; then
    BROAD=true
  fi
}
