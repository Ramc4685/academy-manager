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
#   BROAD            --full or high-risk

# Paths where a mistake is expensive enough to warrant the broad tier: billing,
# tenancy, auth, migrations, composition, webhooks and money routes, the BFF proxy and
# middleware, CI, deployment and dependency manifests. Anchored to real path
# prefixes (case-sensitive): a bare substring like `auth` used to catch
# `authoring.py`, and `billing` caught every billing UI page and e2e spec.
CLASSIFY_HIGH_RISK_RE='^\.github/workflows/|^scripts/|^docker-compose[^/]*\.ya?ml$|(^|/)Dockerfile[^/]*$|(^|/)fly\.toml$|(^|/)requirements[^/]*\.txt$|(^|/)pnpm-lock\.yaml$|(^|/)package\.json$|^backend/v2/(contexts/billing|shared/tenancy|shared/auth|migrations|composition)/|^backend/v2/main\.py$|^backend/v2/contexts/identity/application/use_cases/load_auth_claims\.py$|^backend/v2/interfaces/([^/]+/)?[^/]*webhook[^/]*\.py$|^backend/v2/interfaces/.*(billing|payment|invoice|tenant)[^/]*\.py$|^frontend/middleware\.ts$|^frontend/lib/auth/|^frontend/lib/api/auth-|^frontend/app/api/'

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
    if printf '%s' "$f" | grep -qE "$CLASSIFY_HIGH_RISK_RE"; then
      HIGH_RISK=true
    fi
  done <<< "${changed}"

  if [ "$full" = "--full" ]; then
    RUN_E2E=true
  fi
  # Mixed backend+frontend is no longer broad on its own: the focused tier
  # already checks each side that changed.
  if [ "$full" = "--full" ] || [ "$HIGH_RISK" = true ]; then
    BROAD=true
  fi
}
