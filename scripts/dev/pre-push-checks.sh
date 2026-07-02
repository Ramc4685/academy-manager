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
UPSTREAM_REF="$(git rev-parse --abbrev-ref --symbolic-full-name @{upstream} 2>/dev/null || true)"
BASE=""
if [ -n "${UPSTREAM_REF}" ]; then
  BASE="$(git merge-base HEAD "${UPSTREAM_REF}" 2>/dev/null || true)"
fi
if [ -n "${BASE}" ]; then
  CHANGED="$(git diff --name-only "${BASE}"..HEAD 2>/dev/null || true)"
else
  CHANGED="$(git diff --name-only HEAD~1 HEAD 2>/dev/null || true)"
fi
RUN_E2E=false
if [ "$FULL" = "--full" ] || printf '%s\n' "${CHANGED}" | grep -q "^frontend/e2e/"; then
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
  run_check "pytest v2/tests"        pytest v2/tests -n auto -q --tb=short
fi

# ── Frontend ──────────────────────────────────────────────────────────────────
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
run_check "pnpm lint"      pnpm lint

if [ "$RUN_E2E" = true ]; then
  run_check "pnpm e2e" env CI=true pnpm e2e
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
