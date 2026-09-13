#!/usr/bin/env bash
#
# Unit tests for the command wiring in scripts/dev/saas_staging.sh.
#
# Run:  scripts/dev/saas_staging_test.sh
#
# Every case sources saas_staging.sh and stubs the helpers that would reach
# out to Docker, Mongo, or the backend venv, so the tests are hermetic and
# fast. They cover issue #594: `blno-seed` must not fail just because the
# informational launch-readiness audit reports findings, while the dedicated
# audit commands must stay strict.

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
TARGET="${SCRIPT_DIR}/saas_staging.sh"

failures=0
pass() { printf 'ok   - %s\n' "$1"; }
fail() { printf 'FAIL - %s\n' "$1" >&2; failures=$((failures + 1)); }

# run_case <shell-body> [venv-python]
# Sources saas_staging.sh (which must not run main() when sourced), applies the
# stubs, then runs the body. Prints combined output; returns the body's status.
run_case() {
  local body="$1"
  local venv_python="${2:-/usr/bin/true}"
  bash -c "
    source '${TARGET}'
    compose_mongo_url() { printf 'mongodb://127.0.0.1:27017\n'; }
    VENV_PYTHON='${venv_python}'
    BLNO_SEED_SCRIPT=/dev/null
    ${body}
  " 2>&1
}

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "${haystack}" == *"${needle}"* ]]; then
    pass "${name}"
  else
    fail "${name}: expected output to contain '${needle}'"
    printf '%s\n' "${haystack}" >&2
  fi
}

FAILING_AUDIT='launch_audit() { echo "STUB-AUDIT-REPORT"; return 1; };'

# --- 1. blno-seed succeeds even when the audit reports findings -------------
out="$(run_case "${FAILING_AUDIT} cmd_blno_seed")"; rc=$?
if [[ ${rc} -eq 0 ]]; then
  pass "blno-seed exits 0 when the launch-readiness audit reports findings"
else
  fail "blno-seed exited ${rc}; the audit's findings must not fail the seed (#594)"
  printf '%s\n' "${out}" >&2
fi
assert_contains "blno-seed still prints the audit report" "${out}" "STUB-AUDIT-REPORT"
assert_contains "blno-seed points at the strict audit command" "${out}" "launch-audit"

# --- 2. the same holds through the top-level dispatcher ---------------------
out="$(run_case "${FAILING_AUDIT} main blno-seed")"; rc=$?
if [[ ${rc} -eq 0 ]]; then
  pass "'saas_staging.sh blno-seed' exits 0 when the audit reports findings"
else
  fail "'saas_staging.sh blno-seed' exited ${rc}; expected 0"
  printf '%s\n' "${out}" >&2
fi

# --- 3. a genuinely failing seed still fails --------------------------------
out="$(run_case "launch_audit() { echo unused; }; cmd_blno_seed" /usr/bin/false)"; rc=$?
if [[ ${rc} -ne 0 ]]; then
  pass "blno-seed still fails when the seed script itself fails"
else
  fail "blno-seed exited 0 despite a failing seed script"
  printf '%s\n' "${out}" >&2
fi

# --- 4. the strict audit commands keep propagating the audit's exit code ----
for cmd in launch-audit audit; do
  out="$(run_case "${FAILING_AUDIT} main ${cmd} blno")"; rc=$?
  if [[ ${rc} -ne 0 ]]; then
    pass "'saas_staging.sh ${cmd} blno' exits non-zero on audit failure"
  else
    fail "'saas_staging.sh ${cmd} blno' exited 0; the strict audit must fail loudly"
    printf '%s\n' "${out}" >&2
  fi
done

# --- 5. sourcing the script must not execute a command ----------------------
out="$(bash -c "source '${TARGET}'; printf 'SOURCED-CLEAN\n'")"; rc=$?
if [[ ${rc} -eq 0 && "${out}" == "SOURCED-CLEAN" ]]; then
  pass "sourcing saas_staging.sh does not run main()"
else
  fail "sourcing saas_staging.sh ran main() (exit ${rc})"
  printf '%s\n' "${out}" >&2
fi

if [[ ${failures} -gt 0 ]]; then
  printf '\n%d test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf '\nAll saas_staging.sh tests passed\n'
