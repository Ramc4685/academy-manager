# onboarding-waiver-registration-fix

## Current State

Status: active

## Problem

Registration waiver step errors 'no active waiver to accept' because it reads from empty 'waivers' collection instead of admin-managed 'waiver_templates'

## Changed Files

- None recorded yet.

## Log

- 2026-06-15T09:38:35 main/NA: Task ledger created.
- 2026-06-15T09:51:12 main/done: All phases implemented: MongoRegistrationWaiverRepository, composition rewired, WaiverAcceptance.waiver_template_id, GET /onboarding/waiver BFF, WaiverStep fetches real content, seed updated, legacy repo deleted. 1167 tests pass.
- 2026-06-20T18:39:36 main/working: Investigating production parent onboarding waiver blocker; tracing v2 parent BFF, waiver template lookup, tenant resolution, and frontend error states before editing.
- 2026-06-20T18:45:51 main/working: Implemented compatibility for legacy production published waiver_templates rows with real body text, corrected bootstrap default waiver_template shape, and split frontend waiver load errors from true not-configured state.
- 2026-06-20T18:45:51 main/working: Read-only production check: backend is single_academy PRIMARY_ACADEMY_ID=acad_blno_badminton; academy.courtmastr.com maps to BLNO; waiver_templates has one BLNO Liability Waiver row with status=published, non-empty body, no assigned_to_registration, so current strict active+assigned lookup returns configured:false.
- 2026-06-20T18:52:04 main/working: Added contract coverage for PATCH accept_waiver with the production-shaped published waiver row, plus a mobile Playwright regression that stubs the parent BFF and verifies Waiver text -> I Accept -> Session step.
- 2026-06-20T18:54:59 main/working: Promotion audit: no open PR exists for the waiver fix; current branch feat/coach-day-hub-passport-redesign-local is already merged and contains unrelated billing/admin dirty work, so the waiver fix needs an isolated branch/PR before production deploy. Production workflow deploys only from main after the production approval environment gate.
- 2026-06-20T20:26:41 main/working: Added admin waiver detail registration assignment support: detail API now returns status/assigned fields, detail page can require an active waiver for registration, and stale refetch errors no longer hide successful assignment state.
## Verification

- No verification recorded yet.
- 2026-06-15T09:51:24: pytest v2/tests -q: 1167 passed 0 failed. ruff format --check v2: 631 files formatted. pnpm typecheck: no errors. 5/5 contract tests pass (resolve, unassigned, non-active, tenant-isolation, empty).
- 2026-06-20T18:45:51: Red tests first: production-shaped published waiver row and bootstrap waiver_template shape failed before implementation (2 failed). After fix: pytest backend/v2/tests/contract/test_registration_waiver_repo.py backend/v2/tests/contract/test_mongo_bootstrap_store.py backend/v2/tests/application/test_admin_waiver_template_management.py backend/v2/tests/interface/test_admin_waiver_template_management.py -q => 16 passed, 1 StarletteDeprecationWarning; pytest backend/v2/tests/contract/test_registration_waiver_repo.py -q => 6 passed; ruff format --check + ruff check touched backend files => passed; frontend pnpm typecheck => passed.
- 2026-06-20T18:52:04: Fresh continuation verification: pytest backend/v2/tests/contract/test_registration_waiver_repo.py backend/v2/tests/contract/test_parent_onboarding_waiver_acceptance.py backend/v2/tests/contract/test_mongo_bootstrap_store.py backend/v2/tests/application/test_admin_waiver_template_management.py backend/v2/tests/interface/test_admin_waiver_template_management.py -q => 17 passed, 1 StarletteDeprecationWarning; backend ruff format --check + ruff check touched files => passed; frontend pnpm typecheck => passed; PLAYWRIGHT_PORT=3104 pnpm exec playwright test e2e/specs/qa-defects.spec.ts -g 'parent onboarding shows waiver text' => 2 passed across chromium-mobile and webkit-mobile. Local stack health via scripts/local_test_stack.sh all passed earlier.
- 2026-06-20T18:54:59: Additional promotion checks: gh pr list --state open returned []; gh run list --workflow Production shows latest main production runs successful but none for this waiver fix. frontend pnpm lint => 0 errors, 5 existing warnings; frontend pnpm build => success; backend ruff check v2 && ruff format --check v2 => passed, 661 files already formatted. .worktrees is gitignored, but no isolated worktree was created because explicit consent is required by the worktree workflow.
- 2026-06-20T20:26:41: Admin waiver detail assignment verification: backend RED then green for detail assignment fields; pytest backend/v2/tests/contract/test_admin_waivers_mongo_repo.py backend/v2/tests/interface/test_admin_waiver_template_management.py backend/v2/tests/application/test_admin_waiver_details.py -q => 13 passed, 1 existing StarletteDeprecationWarning; ruff format --check + ruff check touched backend files => passed; pnpm --dir frontend typecheck => passed; pnpm --dir frontend lint => 0 errors, 5 existing warnings; PLAYWRIGHT_PORT=3118 pnpm --dir frontend exec playwright test e2e/specs/admin-waivers.spec.ts => 8 passed. Screenshots captured at output/screenshots/admin-waiver-detail-before-assign.png and output/screenshots/admin-waiver-detail-after-assign.png.
## Reusable Lessons

- None recorded yet.
