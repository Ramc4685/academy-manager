# ci-gate-and-push-process

PR: #477

## What changed
Three process-hardening changes (#473, #474, #475). The Production workflow
gains an always-run aggregate **CI Gate** job that needs every PR job and
fails if any of them failed or was cancelled; jobs skipped by path filters
count as pass, and because the gate always runs on every PR, a missing check
can never be mistaken for success. The release-notes job is named **Release
Notes Gate** so both can be required status checks in a branch-protection
ruleset on `main` (applied via the GitHub API alongside this PR: PRs
required, direct pushes and force pushes blocked). The pre-push hook
(`scripts/dev/pre-push-checks.sh`) is now change-aware and fail-fast:
docs-only pushes skip build/tests, backend-only runs ruff on changed files
plus changed tests and the structural suite, frontend-only runs unit tests,
typecheck, and eslint on changed files; auth/tenancy/billing/Stripe/
migrations/CI/deploy paths or mixed changes still run the full broad tier,
and `--full` preserves the previous comprehensive behavior. AGENTS.md review
policy is relaxed to `/code-review` at PR open plus material revisions.

## Deploy notes
No application deploy. After this PR merges, the ruleset on `main` requires
the "CI Gate" and "Release Notes Gate" checks — open PRs must merge in main
(or rebase) before those contexts report and they become mergeable. No
migrations, no env vars.

## Risk / rollback
The gate treats a skipped upstream job as pass, which is correct for
path-filtered jobs but means a job disabled by mistake would not block; the
gate's own log lists every job result for audit. The lighter local pre-push
tiers shift some failure discovery from push time to PR time — acceptable
because the full 2,719-test suite is now an enforced merge gate instead of
advisory. Rollback: revert the PR (workflow + hook + AGENTS.md) and delete
the `main-protection` ruleset in repo settings; the ruleset alone can be
disabled in the UI without reverting code.
