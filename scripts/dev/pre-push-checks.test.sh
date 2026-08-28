#!/usr/bin/env bash
# pre-push-checks.test.sh — regression tests for the change-tier classifier
# used by scripts/dev/pre-push-checks.sh. Run locally or in CI (Hook
# Classifier Tests job):
#
#   bash scripts/dev/pre-push-checks.test.sh

set -euo pipefail

# shellcheck source=scripts/dev/lib/classify-changes.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/classify-changes.sh"

FAILURES=0
CASES=0

# assert_tier <name> <changed-paths> <full-flag> <docs> <backend> <frontend> <risk> <broad> <e2e>
assert_tier() {
  local name="$1" changed="$2" full="$3"
  local want_docs="$4" want_be="$5" want_fe="$6" want_risk="$7" want_broad="$8" want_e2e="$9"
  CASES=$((CASES + 1))
  classify_changes "$changed" "$full"
  local got="docs=$DOCS_ONLY be=$BACKEND_CHANGED fe=$FRONTEND_CHANGED risk=$HIGH_RISK broad=$BROAD e2e=$RUN_E2E"
  local want="docs=$want_docs be=$want_be fe=$want_fe risk=$want_risk broad=$want_broad e2e=$want_e2e"
  if [ "$got" = "$want" ]; then
    echo "ok   $name"
  else
    echo "FAIL $name"
    echo "     want: $want"
    echo "     got:  $got"
    FAILURES=$((FAILURES + 1))
  fi
}

#           name              changed paths                                              full  docs  be    fe    risk  broad e2e
assert_tier "empty diff"      ""                                                         ""    true  false false false false false
assert_tier "docs only"       $'docs/release-notes/x.md\nREADME.md'                      ""    true  false false false false false
assert_tier "issue template"  '.github/ISSUE_TEMPLATE/bug_report.md'                     ""    true  false false false false false
assert_tier "backend only"    $'backend/v2/contexts/curriculum/service.py\nbackend/v2/tests/unit/test_x.py' \
                                                                                         ""    false true  false false false false
assert_tier "frontend only"   'frontend/app/admin/page.tsx'                              ""    false false true  false false false
assert_tier "billing risk"    'backend/v2/contexts/billing/invoice.py'                   ""    false true  false true  true  false
assert_tier "auth risk"       'frontend/lib/auth/auth-domain.ts'                         ""    false false true  true  true  false
assert_tier "tenancy risk"    'backend/v2/shared/tenancy.py'                             ""    false true  false true  true  false
assert_tier "migration risk"  'backend/v2/migrations/m042_x.py'                          ""    false true  false true  true  false
assert_tier "workflow risk"   '.github/workflows/production.yml'                         ""    false false false true  true  false
assert_tier "scripts risk"    'scripts/dev/pre-push-checks.sh'                           ""    false false false true  true  false
assert_tier "lockfile risk"   'frontend/pnpm-lock.yaml'                                  ""    false false true  true  true  false
assert_tier "mixed be+fe"     $'backend/v2/main.py\nfrontend/app/page.tsx'               ""    false true  true  false true  false
assert_tier "e2e billing"     'frontend/e2e/parent-billing.spec.ts'                      ""    false false true  true  true  true
assert_tier "e2e non-risk"    'frontend/e2e/smoke.spec.ts'                               ""    false false true  false false true
assert_tier "docs + backend"  $'docs/testing.md\nbackend/v2/contexts/curriculum/api.py'  ""    false true  false false false false
assert_tier "full flag docs"  'README.md'                                                "--full" true false false false true true
assert_tier "full flag be"    'backend/v2/contexts/curriculum/service.py'                "--full" false true false false true true

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "All $CASES classifier cases passed."
  exit 0
else
  echo "$FAILURES of $CASES classifier cases FAILED."
  exit 1
fi
