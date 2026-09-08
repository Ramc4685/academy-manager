#!/usr/bin/env bash
# Run a dependency vulnerability audit (pnpm audit / pip-audit) and classify
# the outcome:
#   - clean                          -> exit 0
#   - findings at/above the level    -> exit 1 (blocking, as before)
#   - advisory registry unreachable  -> exit 0 with a ::warning:: unless
#                                       AUDIT_STRICT=1, in which case exit 1
#
# Why: the audit is a blocking step on the production deploy path, and it
# depends on a third-party endpoint. On 2026-09-04 npm's advisories API timed
# out for over an hour (twice, 25 min apart) and blocked a deploy whose code
# had already passed the same audit on its PR. A registry outage is not a
# vulnerability. The nightly workflow runs the same audits with AUDIT_STRICT=1
# so a skipped check on a main run is still caught within a day.
set -uo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <audit command...>" >&2
  exit 2
fi

log_file="$(mktemp)"
trap 'rm -f "${log_file}"' EXIT

"$@" 2>&1 | tee "${log_file}"
status="${PIPESTATUS[0]}"

if [ "${status}" -eq 0 ]; then
  exit 0
fi

# Patterns that mean "could not reach the advisory database", not "vulnerable".
unreachable_re='TimeoutError|The operation was aborted due to timeout|error \(23\)|ENOTFOUND|ECONNRESET|ECONNREFUSED|EAI_AGAIN|ETIMEDOUT|socket hang up|fetch failed|Will retry in|ConnectionError|Max retries exceeded|Temporary failure in name resolution|503 Service Unavailable|502 Bad Gateway|504 Gateway'
# Patterns that mean findings were actually reported.
findings_re='vulnerabilit(y|ies) found|found [0-9]+ known vulnerabilit|^\s*(critical|high|moderate|low)\s*[|│]|severity:|PYSEC-|GHSA-|CVE-[0-9]{4}-'

if grep -Eiq "${findings_re}" "${log_file}"; then
  echo "::error::Dependency audit reported findings (exit ${status})."
  exit "${status}"
fi

if grep -Eiq "${unreachable_re}" "${log_file}"; then
  if [ "${AUDIT_STRICT:-0}" = "1" ]; then
    echo "::error::Dependency audit could not reach the advisory database and AUDIT_STRICT=1 (exit ${status})."
    exit "${status}"
  fi
  echo "::warning::Dependency audit could not reach the advisory database (exit ${status}); treating as inconclusive, not as a failure. The nightly workflow re-runs this audit strictly."
  exit 0
fi

echo "::error::Dependency audit failed for an unrecognised reason (exit ${status}); failing closed."
exit "${status}"
