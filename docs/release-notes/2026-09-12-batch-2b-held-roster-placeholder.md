# batch-2b: held-roster-placeholder

PR: #0

## What changed

- Fixes #728 — Added three mock-API Playwright specs to
  `frontend/e2e/specs/admin-family-billing.spec.ts` covering the family
  billing page's Create invoice, Add charge and Bill this month dialogs,
  which previously had no e2e coverage at all.

## Deploy notes

None. Test-only change (new Playwright specs); no backend or schema
changes, no migrations, no manual steps required.

## Risk / rollback

Low risk — this change only adds e2e test coverage and does not touch
production code paths. If the new specs turn out to be flaky or wrong,
revert this PR; no other rollback steps are needed.
