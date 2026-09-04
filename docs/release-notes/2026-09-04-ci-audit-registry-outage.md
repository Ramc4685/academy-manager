# ci-audit-registry-outage

PR: #652

## What changed
- `scripts/ci/dependency_audit.sh` wraps `pnpm audit` and `pip-audit` in
  the production workflow. Real findings still fail the job. Output that
  only shows the advisory registry was unreachable (timeouts, DNS failures,
  connection resets, 5xx) prints a warning and exits 0 unless
  `AUDIT_STRICT=1`. Anything unrecognised fails closed.
- `nightly-e2e.yml` gains a strict daily re-run of both audits, so an
  inconclusive check on a main run is still caught within a day.

## Deploy notes
No application change. On 2026-09-04 npm's advisories API timed out for
over an hour and blocked the deploy of #644; with this change that run
would have warned and continued to the approval gate.

## Risk / rollback
Low. The only behaviour change is on the "registry unreachable" path,
which previously failed the deploy; findings and unknown errors behave as
before. The daily strict job closes the window. Rollback is reverting this
PR, which restores the bare audit commands.
