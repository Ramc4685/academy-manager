#!/usr/bin/env bash
# pre-push-checks.sh — change-aware, fail-fast local gate. Run before every
# push, or install once via scripts/dev/install-hooks.sh so git runs it
# automatically.
#
# The FULL 2,719-test backend suite and all frontend suites remain the CI
# merge gate (required "CI Gate" check on main). This script only decides how
# much of that to mirror locally, based on what actually changed:
#
#   docs-only      → no build/test checks (seconds)
#   backend-only   → ruff on changed files + changed tests + structural suite
#   frontend-only  → node unit tests, typecheck, lint changed files
#   mixed/high-risk→ full backend suite + full frontend static checks
#   --full         → everything above plus E2E (previous behavior)
#
# High-risk paths (auth, tenancy, billing/Stripe, migrations, CI, deployment,
# shared infra) always escalate to the broad tier.
#
# Usage:
#   scripts/dev/pre-push-checks.sh          # change-aware tiers
#   scripts/dev/pre-push-checks.sh --full   # comprehensive suite + E2E

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

pass() { echo -e "${GREEN}✓${RESET} $*"; }
fail() { echo -e "${RED}✗${RESET} $*"; }
info() { echo -e "${YELLOW}▸${RESET} $*"; }
header() { echo -e "\n${BOLD}$*${RESET}"; }

# Fail-fast: stop at the first failing check instead of running everything.
run_check() {
  local label="$1"; shift
  if "$@" > /tmp/pre-push-out 2>&1; then
    pass "$label"
  else
    fail "$label"
    cat /tmp/pre-push-out
    echo ""
    echo -e "${RED}${BOLD}Check failed — fix before pushing.${RESET}"
    exit 1
  fi
}

# ── Collect changed files vs upstream ─────────────────────────────────────────
FULL="${1:-}"
UPSTREAM_REF="$(git rev-parse --abbrev-ref --symbolic-full-name @{upstream} 2>/dev/null || true)"
BASE=""
if [ -n "${UPSTREAM_REF}" ]; then
  BASE="$(git merge-base HEAD "${UPSTREAM_REF}" 2>/dev/null || true)"
fi
if [ -z "${BASE}" ]; then
  BASE="$(git merge-base HEAD origin/main 2>/dev/null || true)"
fi
if [ -n "${BASE}" ]; then
  CHANGED="$(git diff --name-only "${BASE}"..HEAD 2>/dev/null || true)"
else
  CHANGED="$(git diff --name-only HEAD~1 HEAD 2>/dev/null || true)"
fi

# ── Classify the change ───────────────────────────────────────────────────────
# Tier logic lives in lib/classify-changes.sh, covered by
# scripts/dev/pre-push-checks.test.sh (run in CI as Hook Classifier Tests).
# shellcheck source=scripts/dev/lib/classify-changes.sh
source "$ROOT/scripts/dev/lib/classify-changes.sh"
# shellcheck source=scripts/dev/lib/e2e-projects.sh
source "$ROOT/scripts/dev/lib/e2e-projects.sh"
classify_changes "${CHANGED}" "${FULL}"

if [ "$FULL" = "--full" ]; then
  info "Tier: full (--full requested)"
elif [ "$DOCS_ONLY" = true ]; then
  info "Tier: docs-only — skipping build/test checks (CI Gate still runs the full suite on the PR)"
  echo -e "${GREEN}${BOLD}Docs-only change. Safe to push.${RESET}"
  exit 0
elif [ "$BROAD" = true ]; then
  info "Tier: broad (high-risk or mixed backend+frontend change)"
else
  info "Tier: focused ($([ "$BACKEND_CHANGED" = true ] && echo backend-only || echo frontend-only))"
fi

# ── Backend ───────────────────────────────────────────────────────────────────
if [ "$BACKEND_CHANGED" = true ] || [ "$BROAD" = true ]; then
  header "Backend"
  cd "$BACKEND"

  if ! source .venv/bin/activate 2>/dev/null; then
    fail "backend .venv not found — run: cd backend && python -m venv .venv && pip install -r requirements-dev.txt"
    exit 1
  fi

  if [ "$BROAD" = true ]; then
    run_check "ruff format --check v2" ruff format --check v2
    run_check "ruff check v2"          ruff check v2
    run_check "pytest v2/tests"        pytest v2/tests -n auto -q --tb=short
  else
    # Focused tier: lint only what changed; run the tests mapped to the
    # changed modules (#482) plus the fast structural suite (repo invariants
    # like the route manifest).
    # CI parity: CI lints only `v2` (ruff check v2), and pyproject excludes
    # scripts/ and tests/ — so scope to v2 files and pass --force-exclude so
    # explicitly-named files still honor the configured exclusions (#478).
    CHANGED_PY=()
    while IFS= read -r f; do
      case "$f" in
        backend/v2/*.py)
          rel="${f#backend/}"
          [ -f "$rel" ] || continue
          CHANGED_PY+=("$rel")
          ;;
      esac
    done <<< "${CHANGED}"

    if [ ${#CHANGED_PY[@]} -gt 0 ]; then
      run_check "ruff format --check (changed files)" ruff format --check --force-exclude "${CHANGED_PY[@]}"
      run_check "ruff check (changed files)"          ruff check --force-exclude "${CHANGED_PY[@]}"
    fi

    # Selection lives in lib/select-backend-tests.sh, covered by
    # scripts/dev/pre-push-checks.test.sh: changed test files, mirrored
    # context test dirs, and test files importing a changed module. Empty
    # selection falls back to structural-only, which always runs.
    # shellcheck source=scripts/dev/lib/select-backend-tests.sh
    source "$ROOT/scripts/dev/lib/select-backend-tests.sh"
    SELECTED_TESTS=()
    while IFS= read -r t; do
      [ -n "$t" ] && SELECTED_TESTS+=("$t")
    done < <(select_backend_tests "$(printf '%s\n' ${CHANGED_PY[@]+"${CHANGED_PY[@]}"})")
    if [ ${#SELECTED_TESTS[@]} -gt 0 ]; then
      info "focused tests: ${SELECTED_TESTS[*]}"
    else
      info "no tests mapped to changed modules — running structural suite only"
    fi
    run_check "pytest (focused + structural)" \
      pytest ${SELECTED_TESTS[@]+"${SELECTED_TESTS[@]}"} v2/tests/structural -n auto -q --tb=short
  fi
fi

# ── Frontend ──────────────────────────────────────────────────────────────────
if [ "$FRONTEND_CHANGED" = true ] || [ "$BROAD" = true ]; then
  header "Frontend"
  cd "$FRONTEND"

  # Use Node 22+ (matches CI: actions/setup-node node-version: "22").
  # .ts imports in test files require Node's native strip-types support.
  NODE_BIN="node"
  if [ -f "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
    # shellcheck source=/dev/null
    source "${NVM_DIR:-$HOME/.nvm}/nvm.sh" --no-use 2>/dev/null || true
    NODE_BIN="$(nvm which 22 2>/dev/null || echo node)"
  fi
  # pnpm below is invoked bare (not via $NODE_BIN), so it must also resolve
  # through a Node 22 PATH — corepack's pnpm shim is known to crash under some
  # Node 20.x patch releases (ERR_VM_DYNAMIC_IMPORT_CALLBACK_MISSING).
  case "$NODE_BIN" in
    */bin/node) PATH="$(dirname "$NODE_BIN"):$PATH" ;;
  esac
  # Glob (resolved by node, not the shell) so a new *.node-test.mjs file is
  # picked up automatically; the previous hand-maintained list silently
  # skipped 7 of 19 files, three of which had been red for days.
  run_check "node unit tests" "$NODE_BIN" --no-warnings --test "lib/**/*.node-test.mjs"
  run_check "vitest unit tests" pnpm exec vitest run

  run_check "pnpm typecheck" pnpm typecheck

  if [ "$BROAD" = true ]; then
    run_check "pnpm lint" pnpm lint
  else
    # Focused tier: lint only the changed frontend files eslint can parse.
    CHANGED_FE=()
    while IFS= read -r f; do
      case "$f" in
        frontend/*.ts|frontend/*.tsx|frontend/*.js|frontend/*.jsx|frontend/*.mjs)
          rel="${f#frontend/}"
          [ -f "$rel" ] && CHANGED_FE+=("$rel")
          ;;
      esac
    done <<< "${CHANGED}"
    if [ ${#CHANGED_FE[@]} -gt 0 ]; then
      # --no-warn-ignored: config-ignored files passed explicitly are skipped
      # silently instead of warning, keeping parity with `pnpm lint` (#478).
      run_check "eslint (changed files)" pnpm exec eslint --no-warn-ignored "${CHANGED_FE[@]}"
    else
      info "no lintable frontend files changed — skipping eslint"
    fi
  fi

  if [ "$RUN_E2E" = true ]; then
    # Shard by Playwright project, one run each, mirroring CI's
    # one-job-per-project matrix in .github/workflows/production.yml. CI=true
    # means reuseExistingServer is false, so every shard starts and tears down
    # its own dev server.
    #
    # A single run served all ~500 tests from one long-lived `next dev`
    # server, and specs late in that run timed out against a server the
    # earlier ones had degraded — the logout spec failed at test #514 even on
    # retry, while passing in 15s on its own. CI=true also sets
    # failOnFlakyTests, so each of those retries blocked the push. Sharding
    # keeps every server fresh and each shard about a third the length.
    #
    # Capture the shard list up front and fail loudly if it is unavailable or
    # empty — `for project in $(e2e_projects)` ignored the exit code, so a
    # broken config path silently ran zero shards and passed the gate.
    E2E_PROJECTS="$(e2e_gate_shard_list "" "$FULL")" || {
      fail "e2e shard list unavailable — refusing to skip the e2e gate"
      exit 1
    }
    # Nightly-only shards (webkit) mirror CI: skipped on the PR-style gate,
    # included with --full or PRE_PUSH_E2E_ALL=1. Say so, so a skipped browser
    # is never mistaken for a covered one.
    if [ "$FULL" != "--full" ] && [ "${PRE_PUSH_E2E_ALL:-}" != "1" ]; then
      SKIPPED_NIGHTLY="$(e2e_nightly_only_present | paste -sd ' ' -)"
      if [ -n "$SKIPPED_NIGHTLY" ]; then
        info "E2E nightly-only shard(s) skipped, as on CI PR checks: $SKIPPED_NIGHTLY (use --full or PRE_PUSH_E2E_ALL=1 to include)"
      fi
    fi
    # Pre-flight the e2e port (#522). CI=true forces reuseExistingServer=false,
    # so an existing listener makes every shard fail as a wall of Playwright
    # errors. The port is now derived per-worktree, so a collision usually
    # means a stale dev server from THIS worktree (or an explicit
    # PLAYWRIGHT_PORT clash) — name the cause up front instead.
    E2E_PORT="${PLAYWRIGHT_PORT:-$(
      # shellcheck source=scripts/dev/lib/worktree-port.sh
      . "$ROOT/scripts/dev/lib/worktree-port.sh"
      derive_worktree_port "$(cd "$ROOT" && pwd -P)"
    )}"
    if lsof -nP -iTCP:"$E2E_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      fail "port $E2E_PORT is already in use — the e2e webServer cannot bind (CI=true disables server reuse)."
      echo "Another process owns the e2e port for this worktree (likely a stale 'next dev'," >&2
      echo "or another worktree if you exported PLAYWRIGHT_PORT). Offenders:" >&2
      lsof -nP -iTCP:"$E2E_PORT" -sTCP:LISTEN >&2 || true
      echo "Stop that server (or set PLAYWRIGHT_PORT to a free port) and re-run." >&2
      exit 1
    fi
    while IFS= read -r project; do
      run_check "pnpm e2e ($project)" env CI=true pnpm exec playwright test --project="$project"
    done <<< "$E2E_PROJECTS"
  else
    info "E2E skipped (no e2e/ files changed) — use --full to force"
  fi
fi

# ── Result ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}All checks passed. Safe to push.${RESET}"
exit 0
