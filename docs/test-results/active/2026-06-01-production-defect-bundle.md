# production defect bundle

## Current State

Status: active

## Problem

Sessions are not showing; admin student profile needs enrolled sessions, payment history, and current payment amount; register-child workflow needs local verification before production.

## Changed Files

- `backend/v2/composition/admin.py`
- `backend/v2/contexts/enrollment/application/use_cases/admin_directory.py`
- `backend/v2/contexts/enrollment/infrastructure/mongo_session_repo.py`
- `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`
- `backend/v2/interfaces/admin/views.py`
- `backend/v2/tests/contract/test_admin_directory_mongo_student_repo.py`
- `backend/v2/tests/interface/test_admin_sessions.py`
- `backend/v2/tests/interface/test_admin_student_user_routes.py`
- `backend/v2/tests/interface/test_parent_sessions_checkout.py`
- `frontend/app/(marketing)/register/page.tsx`
- `frontend/app/(marketing)/login/page.tsx`
- `frontend/app/(admin)/admin/students/[studentId]/page.tsx`
- `frontend/e2e/specs/admin-students.spec.ts`
- `frontend/e2e/specs/register-email-verification.spec.ts`
- `frontend/lib/api/v2/students.ts`
- `frontend/lib/auth/firebase.ts`
- `frontend/lib/auth/parent-registration-continuation.ts`

## Log

- 2026-06-01T07:45:44 main/NA: Task ledger created.
- 2026-06-01T07:45:51 main/working: Pre-split ledger preserved in docs/test-results/archive/2026-06-01-pre-split-test-result.md. Current session visibility slice is implemented and focused pytest/ruff checks were previously recorded in the archived ledger; authenticated local/browser retest remains pending.
- 2026-06-01T07:50:13 main/working: Task 2 session visibility fixes extended after review: reservations now use the same session-id/ObjectId lookup as get(), recurring admin date synthesis uses selected local session date semantics for late local classes, and focused regressions cover ObjectId-backed legacy templates plus late America/Chicago sessions. Verification passed locally: backend focused pytest for parent session checkout and admin sessions returned 31 passed; ruff check v2 passed; ruff format --check v2 passed; git diff --check passed. Authenticated local/browser retest still pending due local auth token blocker.
- 2026-06-01T07:59:26 main/working: Task 2 final quality cleanup: ObjectId-backed legacy templates now use the same lookup semantics for repository get/get_many, reservation, release, and status update; parent catalog concrete-session query is bounded to the same 30-day window. Verification passed after formatting: backend focused pytest returned 31 passed; ruff check v2 passed; ruff format v2/contexts/enrollment/infrastructure/mongo_session_repo.py reformatted one touched file; ruff format --check v2 then passed; git diff --check passed.
- 2026-06-01T08:04:24 main/working: Task 3 backend admin student detail enrichment started. Current detail path lacks enrolled session/payment/current payment fields; adding Mongo contract tests first, then application/interface models and repository enrichment.
- 2026-06-01T08:08:54 main/working: Task 3 backend admin student detail BFF enrichment implemented. Added application/interface models, scoped Mongo detail enrichment, contract coverage for tenant/student scoping plus invoice/session-price current payment rules, and BFF serialization coverage. Touched files: backend/v2/contexts/enrollment/application/use_cases/admin_directory.py, backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py, backend/v2/interfaces/admin/views.py, backend/v2/tests/contract/test_admin_directory_mongo_student_repo.py, backend/v2/tests/interface/test_admin_student_user_routes.py.
- 2026-06-01T08:36:02 main/working: Task 3 backend student detail enrichment payment normalization fixed locally: current payment now includes failed/expired open balances, honors final_amount/discount/balance fields, treats paid/succeeded rows without explicit paid fields as paid, caps/sorts payment history query, and adds Mongo contract regressions. Verification: backend focused pytest for admin directory/edit/student routes passed (19 passed); ruff check v2 passed; ruff format --check v2 passed; git diff --check passed.
- 2026-06-01T08:44:22 main/working: Task 3 backend reviewer stale-balance finding fixed: paid/succeeded rows now normalize balance_due_cents to 0 before honoring stored balance_due_cents, and contract coverage seeds a succeeded row with stale balance_due_cents. Verification: backend focused pytest passed (19 passed); ruff format --check v2 passed; ruff check v2 passed; git diff --check passed. Task 4 frontend student detail UI now renders current payment, enrolled sessions, and payment history. Verification: pnpm typecheck passed; pnpm lint passed; PLAYWRIGHT_PORT=3101 pnpm exec playwright test e2e/specs/admin-students.spec.ts --project=chromium-mobile passed (4 passed).
- 2026-06-02T20:15:38 main/working: Investigating GitHub Actions run 26848747368 for PR #132; only Frontend E2E Chromium/WebKit failed, backend and static jobs passed.
- 2026-06-02T20:16:35 main/working: Root cause found for run 26848747368: coach session detail preserved only ApiError.message in row state, while E2E and offline conflict UX require structured error code visibility for 409 attendance conflicts.
- 2026-06-02T20:34:40 main/working: Follow-up CI run 26858112085 fixed original coach conflict path in Chromium, but WebKit reported a flaky register-email-verification navigation race. Stabilizing the test to use the rendered Sign in link after resend state settles instead of direct page.goto('/login').
## Verification

- 2026-06-01T08:09:04: cd backend && source .venv/bin/activate && ruff format --check v2 => 473 files already formatted
- 2026-06-01T08:09:04: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_admin_directory_mongo_student_repo.py v2/tests/application/test_admin_student_edit.py v2/tests/interface/test_admin_student_user_routes.py -q => 18 passed in 1.18s
- 2026-06-01T08:09:04: git diff --check => passed with no whitespace errors
- 2026-06-01T08:09:04: cd backend && source .venv/bin/activate && ruff check v2 => All checks passed
- 2026-06-01T08:52:05: Production defect bundle focused local verification complete. Session visibility backend tests passed (admin sessions + parent sessions checkout), student profile backend and frontend tests passed, and register-child email verification/onboarding E2E passed. Final focused backend bundle passed: 50 passed with ruff format --check v2, ruff check v2, and git diff --check clean. Frontend checks passed: pnpm typecheck, pnpm lint, and PLAYWRIGHT_PORT=3103 pnpm exec playwright test e2e/specs/admin-students.spec.ts e2e/specs/register-email-verification.spec.ts --project=chromium-mobile (5 passed). Browser smoke on http://localhost:3104 verified /login -> Register your child -> /register rendered signup controls with no fresh console errors.
- 2026-06-02T20:21:35: CI failure reproduction/fix verification: with PORT=3105 NEXT_PUBLIC_E2E_AUTH_BYPASS=1 npm run dev, ran PLAYWRIGHT_PORT=3105 ./node_modules/.bin/playwright test e2e/specs/coach-today.spec.ts --project=chromium-mobile --grep 'server conflict surfaces a structured error' => 1 passed; same command with --project=webkit-mobile => 1 passed; full coach-today spec both projects => 6 passed, 2 skipped. Frontend static checks: npm run typecheck passed; npm run lint passed.
- 2026-06-02T20:24:49: Pre-push verification passed via temporary pnpm shim: scripts/dev/pre-push-checks.sh => ruff format --check v2 passed, ruff check v2 passed, pytest v2/tests passed, frontend node unit tests passed, pnpm typecheck passed, pnpm lint passed; E2E skipped by script because no frontend/e2e files changed. Script emitted existing integer-expression warning from E2E change detector but exited 0.
- 2026-06-02T20:37:23: WebKit CI flake stabilization verification: npm exec --yes pnpm@10.24.0 -- exec playwright test e2e/specs/register-email-verification.spec.ts --project=webkit-mobile --repeat-each=10 --workers=2 => 10 passed; npm exec --yes pnpm@10.24.0 -- exec playwright test --project=webkit-mobile => 69 passed, 10 skipped. The previously flaky register-email-verification spec passed inside the full WebKit project.
- 2026-06-02T20:42:05: Waiver E2E stub fix verification: npm exec --yes pnpm@10.24.0 -- exec playwright test e2e/specs/saas-parent-waivers.spec.ts --project=chromium-mobile --project=webkit-mobile => 6 passed. Added explicit GET /api/v2/admin/waivers/templates stub so template-management query does not fall through to local backend proxy during full E2E.
## Reusable Lessons

- None recorded yet.
