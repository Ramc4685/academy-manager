#!/usr/bin/env bash
# pre-push-checks.sh — mirrors CI exactly. Run before every push, or install
# once via scripts/dev/install-hooks.sh so git runs it automatically.
#
# Usage:
#   scripts/dev/pre-push-checks.sh          # skip E2E unless e2e/ files changed
#   scripts/dev/pre-push-checks.sh --full   # always run E2E

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

ERRORS=0

run_check() {
  local label="$1"; shift
  if "$@" > /tmp/pre-push-out 2>&1; then
    pass "$label"
  else
    fail "$label"
    cat /tmp/pre-push-out
    ERRORS=$((ERRORS + 1))
  fi
}

# ── Detect whether E2E should run ─────────────────────────────────────────────
FULL="${1:-}"
CHANGED=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || true)
E2E_CHANGED=$(echo "$CHANGED" | grep -c "^frontend/e2e/" 2>/dev/null || echo 0)
RUN_E2E=false
if [ "$FULL" = "--full" ] || [ "$E2E_CHANGED" -gt 0 ]; then
  RUN_E2E=true
fi

# ── Backend ───────────────────────────────────────────────────────────────────
header "Backend"
cd "$BACKEND"

if ! source .venv/bin/activate 2>/dev/null; then
  fail "backend .venv not found — run: cd backend && python -m venv .venv && pip install -r requirements.txt"
  ERRORS=$((ERRORS + 1))
else
  run_check "ruff format --check v2" ruff format --check v2
  run_check "ruff check v2"          ruff check v2
  run_check "pytest v2/tests"        pytest v2/tests -q --tb=short
fi

# ── Frontend ──────────────────────────────────────────────────────────────────
header "Frontend"
cd "$FRONTEND"

run_check "node unit tests" node --no-warnings --test \
  lib/api/proxy-headers.node-test.mjs \
  lib/api/auth-token.node-test.mjs \
  lib/auth/token-readiness.node-test.mjs

run_check "pnpm typecheck" pnpm typecheck
run_check "pnpm lint"      pnpm lint

if [ "$RUN_E2E" = true ]; then
  run_check "pnpm e2e" env CI=1 pnpm e2e
else
  info "E2E skipped (no e2e/ files changed) — use --full to force"
fi

# ── Result ────────────────────────────────────────────────────────────────────
echo ""
if [ $ERRORS -eq 0 ]; then
  echo -e "${GREEN}${BOLD}All checks passed. Safe to push.${RESET}"
  exit 0
else
  echo -e "${RED}${BOLD}$ERRORS check(s) failed — fix before pushing.${RESET}"
  exit 1
fi
