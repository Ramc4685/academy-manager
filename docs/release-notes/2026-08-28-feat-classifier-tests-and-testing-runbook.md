# classifier-tests-and-testing-runbook

PR: #486

## What changed
The pre-push hook's change-tier classifier moved into a sourceable library
(`scripts/dev/lib/classify-changes.sh`) with no behavior change, and gained
18 committed regression cases (`scripts/dev/pre-push-checks.test.sh`)
covering docs-only, backend-only, frontend-only, every high-risk escalation
(auth, tenancy, billing, migrations, workflows, scripts, lockfiles), mixed
changes, e2e detection, empty diffs, and `--full`. A new always-run Hook
Classifier Tests CI job executes them on every PR and is required via CI
Gate's needs — `scripts/**` is not covered by any path filter, so this job
is what makes classifier regressions visible to CI at all (#481). The
Pre-Push Checks section of `docs/testing.md` now documents the tiered hook
from PR #477 instead of the old always-full behavior (#479).

## Deploy notes
None. No application code, no migrations, no env vars. The new CI job adds
one small always-run runner (~30s) per PR.

## Risk / rollback
The hook refactor is an extraction — the classifier logic is the same rules,
now shared with the tests; behavioral drift would fail the 18 committed
cases. The always-run test job slightly increases CI cost per PR and, being
in CI Gate's needs, a red classifier test blocks merges — intended. Revert
the PR to restore the inline classifier and old docs.
