# hook-lint-parity-and-approval-gate

PR: #483

## What changed
Two follow-ups to the #477 process hardening. The focused pre-push tier now
matches CI's lint scope exactly (#478): backend linting is limited to
`backend/v2/*.py` and ruff gets `--force-exclude`, so explicitly-named files
honor pyproject's `extend-exclude` (`scripts/` is dropped; `v2/tests` is
linted, which is what CI's `ruff check v2` traversal does), and the focused
eslint call adds `--no-warn-ignored` so config-ignored files passed
explicitly are skipped silently. `production-approval` in the Production
workflow now depends on `ci-gate` and requires `result == 'success'` instead
of per-job `!= 'failure'` checks (#480), so a cancelled validation job can no
longer proceed toward deployment.

## Deploy notes
None. No application code, no migrations, no env vars. The next push to main
exercises the new approval condition.

## Risk / rollback
The approval gate is strictly tighter (success required rather than absence
of failure); the only behavior change on the deploy path is that cancelled
runs now stop before the production environment gate. The hook change only
loosens local linting to CI's actual scope — anything it stops flagging was
never checked in CI. Revert the PR to restore the previous behavior.
