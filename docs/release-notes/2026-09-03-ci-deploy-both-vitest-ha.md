# ci-deploy-both-vitest-ha

PR: #640

## What changed
- On a push to `main`, every validation job now runs and both the backend
  and the frontend deploy unconditionally. Pull requests keep path-filtered
  validation. `Production Approval`, both deploy jobs and `Production Smoke`
  no longer depend on the `Detect Changes` job. This closes the hole where a
  queued main run cancelled by concurrency never had its diff evaluated, so a
  later backend-only run skipped the frontend deploy (2026-08-30: the
  frontend ran about 24 hours behind the backend).
- `flyctl deploy` now passes `--ha=false`. The app runs one machine on
  purpose (in-process scheduler, boot-time migrations); the default would
  create two whenever the process group is at zero, doubling the bill and
  double-running the scheduled jobs.
- Frontend unit tests run in CI for the first time: `pnpm test:unit` (vitest,
  98 tests) and `pnpm test:node` (node `--test`, 89 tests) are new steps in
  `Frontend Static`. vitest is scoped to `*.test.ts(x)` so it no longer
  collects Playwright specs. The pre-push hook globs `lib/**/*.node-test.mjs`
  instead of a hand-maintained list that skipped 7 of 19 files, and also runs
  vitest.
- The three `admin-billing-reconciliation-ui` node tests, red since the
  payments page was split in the Rally restyle, now read the panel, format
  and dialog modules the symbols moved to.

## Deploy notes
No application code changes. The first push to `main` after this merges
runs the full validation set and then deploys both components after the
usual approval click; a docs-only merge also deploys from now on. Watch the
Fly release for the `--ha=false` flag being accepted (flyctl 0.3+).

## Risk / rollback
Low. Main runs take a few minutes longer for docs-only or single-component
changes because nothing is skipped. If a new frontend unit-test step turns
out flaky it blocks `CI Gate` like any other job; revert the step or the
test. Rollback is reverting this PR, which restores path-filtered deploys
and the default `--ha` behaviour.
