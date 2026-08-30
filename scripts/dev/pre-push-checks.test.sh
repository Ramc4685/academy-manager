#!/usr/bin/env bash
# pre-push-checks.test.sh — regression tests for the change-tier classifier
# used by scripts/dev/pre-push-checks.sh. Run locally or in CI (Hook
# Classifier Tests job):
#
#   bash scripts/dev/pre-push-checks.test.sh

set -euo pipefail

# shellcheck source=scripts/dev/lib/classify-changes.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/classify-changes.sh"
# shellcheck source=scripts/dev/lib/select-backend-tests.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/select-backend-tests.sh"
# shellcheck source=scripts/dev/lib/e2e-projects.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/e2e-projects.sh"

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

# ── Focused-test selection (select_backend_tests, #482) ──────────────────────
# Hermetic fixture tree standing in for v2/tests.
FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT
mkdir -p "$FIXTURE/contexts/billing" "$FIXTURE/unit"
printf 'from v2.contexts.billing.invoice import Invoice\n' > "$FIXTURE/unit/test_invoice_math.py"
printf 'import v2.shared.tenancy\n' > "$FIXTURE/unit/test_tenancy_guard.py"
printf 'def test_ok(): pass\n' > "$FIXTURE/contexts/billing/test_ledger.py"

# assert_select <name> <changed-paths> <expected-output>
assert_select() {
  local name="$1" changed="$2" want="$3"
  CASES=$((CASES + 1))
  local got
  got="$(select_backend_tests "$changed" "$FIXTURE")"
  if [ "$got" = "$want" ]; then
    echo "ok   $name"
  else
    echo "FAIL $name"
    echo "     want: $(printf '%s' "$want" | tr '\n' ' ')"
    echo "     got:  $(printf '%s' "$got" | tr '\n' ' ')"
    FAILURES=$((FAILURES + 1))
  fi
}

assert_select "changed test file passes through" \
  'v2/tests/unit/test_x.py' \
  'v2/tests/unit/test_x.py'
assert_select "context source maps to mirrored dir + importing test" \
  'v2/contexts/billing/invoice.py' \
  "$FIXTURE/contexts/billing
$FIXTURE/unit/test_invoice_math.py"
assert_select "shared module found via import grep" \
  'v2/shared/tenancy.py' \
  "$FIXTURE/unit/test_tenancy_guard.py"
assert_select "unmapped module selects nothing (structural fallback)" \
  'v2/contexts/onboarding/wizard.py' \
  ''
assert_select "non-python change selects nothing" \
  'v2/contexts/billing/README.txt' \
  ''
assert_select "empty input selects nothing" \
  '' \
  ''

# ── e2e project sharding ──────────────────────────────────────────────────────
# The gate runs one Playwright invocation per project (mirroring CI's
# one-job-per-project matrix), reading the list from playwright.config.ts so a
# project added there is never silently skipped locally.

# assert_projects <name> <config-contents> <expected-newline-separated>
assert_projects() {
  local name="$1" contents="$2" want="$3"
  CASES=$((CASES + 1))
  local tmp
  tmp="$(mktemp)"
  printf '%s\n' "$contents" > "$tmp"
  local got
  got="$(e2e_projects "$tmp" || true)"
  rm -f "$tmp"
  if [ "$got" = "$want" ]; then
    echo "ok   $name"
  else
    echo "FAIL $name"
    echo "     want: $want"
    echo "     got:  $got"
    FAILURES=$((FAILURES + 1))
  fi
}

assert_projects "reads project names in config order" \
  '  projects: [
    {
      name: "chromium-mobile",
      use: { ...devices["Pixel 7"] },
    },
    {
      name: "webkit-mobile",
    },
  ],' \
  'chromium-mobile
webkit-mobile'
assert_projects "a project added to the config is picked up" \
  '      name: "chromium-mobile",
      name: "webkit-mobile",
      name: "firefox-desktop",' \
  'chromium-mobile
webkit-mobile
firefox-desktop'
assert_projects "config with no projects yields nothing" \
  '  use: { baseURL: "http://localhost:3001" },' \
  ''

CASES=$((CASES + 1))
if e2e_projects "/nonexistent/playwright.config.ts" >/dev/null 2>&1; then
  echo "FAIL missing config is an error, not a silent empty shard list"
  FAILURES=$((FAILURES + 1))
else
  echo "ok   missing config is an error, not a silent empty shard list"
fi

# ── e2e_shard_list: never degrade to zero shards ─────────────────────────────
# pre-push-checks.sh iterates over e2e_shard_list, which must turn a missing
# config or an empty project list into a hard error instead of an empty loop
# that skips every e2e shard while the gate exits 0.

CASES=$((CASES + 1))
if e2e_shard_list "/nonexistent/playwright.config.ts" >/dev/null 2>&1; then
  echo "FAIL e2e_shard_list fails on a missing config"
  FAILURES=$((FAILURES + 1))
else
  echo "ok   e2e_shard_list fails on a missing config"
fi

CASES=$((CASES + 1))
EMPTY_CONFIG="$(mktemp)"
printf '  use: { baseURL: "http://localhost:3001" },\n' > "$EMPTY_CONFIG"
if e2e_shard_list "$EMPTY_CONFIG" >/dev/null 2>&1; then
  echo "FAIL e2e_shard_list fails on a config with no projects"
  FAILURES=$((FAILURES + 1))
else
  echo "ok   e2e_shard_list fails on a config with no projects"
fi
rm -f "$EMPTY_CONFIG"

CASES=$((CASES + 1))
SHARD_CONFIG="$(mktemp)"
printf '      name: "chromium-mobile",\n      name: "webkit-mobile",\n' > "$SHARD_CONFIG"
GOT_SHARDS="$(e2e_shard_list "$SHARD_CONFIG" || true)"
rm -f "$SHARD_CONFIG"
if [ "$GOT_SHARDS" = 'chromium-mobile
webkit-mobile' ]; then
  echo "ok   e2e_shard_list echoes the project list on success"
else
  echo "FAIL e2e_shard_list echoes the project list on success"
  echo "     got:  $GOT_SHARDS"
  FAILURES=$((FAILURES + 1))
fi

# The real config must expose every project CI runs as its own job, or the
# local gate would skip a browser CI still enforces.
CASES=$((CASES + 1))
REAL_CONFIG="$(cd "$(dirname "$0")/../.." && pwd)/frontend/playwright.config.ts"
REAL_PROJECTS="$(e2e_projects "$REAL_CONFIG" | sort | tr '\n' ' ')"
if [ "$REAL_PROJECTS" = "chromium-desktop chromium-mobile webkit-mobile " ]; then
  echo "ok   real playwright.config.ts exposes the three CI projects"
else
  echo "FAIL real playwright.config.ts exposes the three CI projects"
  echo "     want: chromium-desktop chromium-mobile webkit-mobile "
  echo "     got:  $REAL_PROJECTS"
  FAILURES=$((FAILURES + 1))
fi

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "All $CASES cases passed."
  exit 0
else
  echo "$FAILURES of $CASES cases FAILED."
  exit 1
fi
