#!/usr/bin/env bash
# pre-push-checks.sh — mirrors CI exactly. Run before every push, or install
# once via scripts/dev/install-hooks.sh so git runs it automatically.
#
# Usage:
#   scripts/dev/pre-push-checks.sh          # skip E2E unless e2e/ files changed
#   scripts/dev/pre-push-checks.sh --full   # always run E2E
#
# Parallelism:
#   - Backend group and Frontend group run concurrently.
#   - Within Frontend, typecheck and lint run concurrently.
#   - pytest uses -n auto (pytest-xdist) when available for ~4-5x speedup.
#
# Install pytest-xdist once to unlock the biggest win:
#   cd backend && source .venv/bin/activate && pip install pytest-xdist

set -uo pipefail

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

# ── Detect whether E2E should run ─────────────────────────────────────────────
FULL="${1:-}"
CHANGED=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || true)
E2E_CHANGED=$(echo "$CHANGED" | grep -c "^frontend/e2e/" 2>/dev/null || true)
RUN_E2E=false
if [ "$FULL" = "--full" ] || [ "$E2E_CHANGED" -gt 0 ]; then
  RUN_E2E=true
fi
if [ "${SKIP_E2E:-}" = "1" ]; then
  RUN_E2E=false
fi

# ── Per-check temp files (fixes shared /tmp/pre-push-out race condition) ──────
TMPDIR_CHECKS="$(mktemp -d /tmp/pre-push-XXXXXX)"
trap 'rm -rf "$TMPDIR_CHECKS"' EXIT

# run_check_bg LABEL OUTFILE CMD...
# Runs CMD in background; writes exit-code to OUTFILE.exit, stdout+stderr to OUTFILE.log
run_check_bg() {
  local label="$1" outfile="$2"; shift 2
  (
    if "$@" > "$outfile.log" 2>&1; then
      echo 0 > "$outfile.exit"
    else
      echo 1 > "$outfile.exit"
    fi
  ) &
}

print_result() {
  local label="$1" outfile="$2"
  local code
  code=$(cat "$outfile.exit" 2>/dev/null || echo 1)
  if [ "$code" = "0" ]; then
    pass "$label"
  else
    fail "$label"
    cat "$outfile.log"
    return 1
  fi
}

# ── Backend group (background) ────────────────────────────────────────────────
run_backend() {
  cd "$BACKEND"

  if ! source .venv/bin/activate 2>/dev/null; then
    echo "backend .venv not found — run: cd backend && python -m venv .venv && pip install -r requirements.txt" \
      > "$TMPDIR_CHECKS/backend-venv.log"
    echo 1 > "$TMPDIR_CHECKS/backend-venv.exit"
    return 1
  fi

  # ruff format and ruff check in parallel (both trivial)
  run_check_bg "ruff format --check v2" "$TMPDIR_CHECKS/ruff-fmt" ruff format --check v2
  run_check_bg "ruff check v2"          "$TMPDIR_CHECKS/ruff-chk" ruff check v2

  # pytest: use -n auto when pytest-xdist is installed (830 tests → ~4-5x faster)
  if python -c "import xdist" 2>/dev/null; then
    run_check_bg "pytest v2/tests" "$TMPDIR_CHECKS/pytest" \
      pytest v2/tests -q --tb=short -n auto
  else
    run_check_bg "pytest v2/tests" "$TMPDIR_CHECKS/pytest" \
      pytest v2/tests -q --tb=short
  fi

  wait
}

run_backend &
backend_pid=$!

# ── Frontend group (concurrent with backend) ──────────────────────────────────
run_frontend() {
  cd "$FRONTEND"

  # node unit tests, typecheck, lint — all independent, all in parallel
  run_check_bg "node unit tests" "$TMPDIR_CHECKS/node-tests" \
    node --no-warnings --test \
      lib/api/proxy-headers.node-test.mjs \
      lib/api/auth-token.node-test.mjs \
      lib/auth/token-readiness.node-test.mjs

  run_check_bg "pnpm typecheck" "$TMPDIR_CHECKS/typecheck" pnpm typecheck
  run_check_bg "pnpm lint"      "$TMPDIR_CHECKS/lint"      pnpm lint

  wait
}

run_frontend &
frontend_pid=$!

# ── Wait for both groups ──────────────────────────────────────────────────────
wait "$backend_pid" || true
wait "$frontend_pid" || true

# ── Print results in order ────────────────────────────────────────────────────
ERRORS=0

header "Backend"
if [ -f "$TMPDIR_CHECKS/backend-venv.exit" ]; then
  fail "backend .venv not found — run: cd backend && python -m venv .venv && pip install -r requirements.txt"
  ERRORS=$((ERRORS + 1))
else
  for check in ruff-fmt ruff-chk pytest; do
    case "$check" in
      ruff-fmt) label="ruff format --check v2" ;;
      ruff-chk) label="ruff check v2" ;;
      pytest)   label="pytest v2/tests" ;;
    esac
    print_result "$label" "$TMPDIR_CHECKS/$check" || ERRORS=$((ERRORS + 1))
  done
fi

header "Frontend"
for check in node-tests typecheck lint; do
  case "$check" in
    node-tests) label="node unit tests" ;;
    typecheck)  label="pnpm typecheck" ;;
    lint)       label="pnpm lint" ;;
  esac
  print_result "$label" "$TMPDIR_CHECKS/$check" || ERRORS=$((ERRORS + 1))
done

# E2E runs after everything else (needs the dev stack, sequential is correct)
if [ "$RUN_E2E" = true ]; then
  cd "$FRONTEND"
  if env CI=1 pnpm e2e > "$TMPDIR_CHECKS/e2e.log" 2>&1; then
    pass "pnpm e2e"
  else
    fail "pnpm e2e"
    cat "$TMPDIR_CHECKS/e2e.log"
    ERRORS=$((ERRORS + 1))
  fi
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
