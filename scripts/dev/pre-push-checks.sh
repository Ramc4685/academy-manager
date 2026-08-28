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
    # Focused tier: lint only what changed; run changed tests plus the fast
    # structural suite (repo invariants like the route manifest).
    # CI parity: CI lints only `v2` (ruff check v2), and pyproject excludes
    # scripts/ and tests/ — so scope to v2 files and pass --force-exclude so
    # explicitly-named files still honor the configured exclusions (#478).
    CHANGED_PY=()
    CHANGED_TESTS=()
    while IFS= read -r f; do
      case "$f" in
        backend/v2/*.py)
          rel="${f#backend/}"
          [ -f "$rel" ] || continue
          CHANGED_PY+=("$rel")
          case "$rel" in
            v2/tests/*) CHANGED_TESTS+=("$rel") ;;
          esac
          ;;
      esac
    done <<< "${CHANGED}"

    if [ ${#CHANGED_PY[@]} -gt 0 ]; then
      run_check "ruff format --check (changed files)" ruff format --check --force-exclude "${CHANGED_PY[@]}"
      run_check "ruff check (changed files)"          ruff check --force-exclude "${CHANGED_PY[@]}"
    fi
    run_check "pytest (changed tests + structural)" \
      pytest ${CHANGED_TESTS[@]+"${CHANGED_TESTS[@]}"} v2/tests/structural -n auto -q --tb=short
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
  run_check "node unit tests" "$NODE_BIN" --no-warnings --test \
    lib/canonical-host.node-test.mjs \
    lib/brand.node-test.mjs \
    lib/parent-home.node-test.mjs \
    lib/api/auth-bridge-cookie.node-test.mjs \
    lib/api/auth-token.node-test.mjs \
    lib/api/proxy-headers.node-test.mjs \
    lib/api/token-readiness.node-test.mjs \
    lib/auth/auth-domain.node-test.mjs \
    lib/auth/google-sign-in-mode.node-test.mjs \
    lib/auth/token-readiness.node-test.mjs \
    lib/navigation/admin-student-progress-return.node-test.mjs

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
    run_check "pnpm e2e" env CI=true pnpm e2e
  else
    info "E2E skipped (no e2e/ files changed) — use --full to force"
  fi
fi

# ── Result ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}All checks passed. Safe to push.${RESET}"
exit 0
