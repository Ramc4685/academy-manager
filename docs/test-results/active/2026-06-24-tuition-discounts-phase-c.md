# tuition discounts phase c

## Current State

Status: active

## Problem

Verify read-only legacy discount candidate listing and Playwright coverage for admin discount badges plus parent invoice discount itemization

## Changed Files

- None recorded yet.

## Log

- 2026-06-24T07:25:26 main/NA: Task ledger created.
- 2026-06-24T07:26:55 main/working: Added read-only MongoTuitionDiscountBackfillCandidateQuery with contract coverage for below-price enrollments that lack active discount policies; focused RED failed on missing class, GREEN now passes and asserts no collection count changes.
## Verification

- No verification recorded yet.
- 2026-06-24T07:30:07: Backend RED/GREEN: backend/.venv/bin/python3 -m pytest backend/v2/tests/contract/test_tuition_discount_backfill_candidates.py -q first failed on missing MongoTuitionDiscountBackfillCandidateQuery, then passed after implementation: 1 passed. E2E initial focused run failed on ambiguous test selector after first discount changed the button text to Edit discount; selector tightened to exact Discount.
- 2026-06-24T07:31:18: Focused Phase C checks: ruff format applied to tuition_discounts.py, then ruff format --check and ruff check passed on touched backend files; pytest test_tuition_discount_backfill_candidates.py test_mongo_tuition_discount_repo.py test_tuition_discount_use_cases.py -q -> 9 passed; frontend npx tsc --noEmit passed; npm run lint passed with 5 existing warnings and 0 errors; focused Playwright chromium-mobile tuition-discounts.spec.ts -> 2 passed.
- 2026-06-24T07:36:49: Full frontend npm run e2e attempted: 190 passed, 30 skipped, 2 failed in existing chromium-mobile specs (admin-shell logout timeout and coach-day-hub-passport navigation timeout); new tuition-discounts.spec.ts passed in both chromium-mobile and webkit-mobile during that run. Immediate focused rerun of the two failed existing specs passed: 2 passed.
- 2026-06-24T07:45:32: Pre-push --full first attempt failed in existing saas-parent-waivers template-version spec on a 500 console error from a missing current waiver id/detail fixture; fixed the E2E fixture with exact route matches plus wt-current detail stub. Focused rerun for that spec on chromium-mobile and webkit-mobile passed: 2 passed.
- 2026-06-24T07:54:14: Pre-push --full second attempt still failed in saas-parent-waivers template-version spec under full-suite ordering. Added stubAcademy to the admin waiver specs so the shell academy request is mocked; focused rerun on chromium-mobile and webkit-mobile passed: 2 passed.
- 2026-06-24T08:02:04: Pre-push --full third attempt failed in existing saas-attendance-billing admin generate-monthly spec on a 500 console error from an unstubbed admin academy shell request; added stubAcademy. Focused rerun on chromium-mobile and webkit-mobile passed: 2 passed.
- 2026-06-24T08:09:19: Full pre-push gate: scripts/dev/pre-push-checks.sh --full -> backend ruff format/check passed, backend pytest v2/tests passed, frontend node unit tests passed, pnpm typecheck passed, pnpm lint passed, pnpm e2e passed; exit 0.
## Reusable Lessons

- None recorded yet.
