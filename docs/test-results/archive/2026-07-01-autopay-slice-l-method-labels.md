# autopay slice l method labels

## Current State

Status: active

## Problem

R6 parent visibility requires payment method type and last4/bank label when available; current Slice V exposes type only and parent customer projection lacks display details.

## Changed Files

- `backend/v2/composition/parent.py`
- `backend/v2/contexts/billing/application/ports.py`
- `backend/v2/contexts/billing/application/use_cases/parent_billing.py`
- `backend/v2/contexts/billing/infrastructure/mongo_parent_billing_customer_repo.py`
- `backend/v2/interfaces/parent/views.py`
- `backend/v2/migrations/0144_parent_payment_method_display.py`
- `backend/v2/tests/application/test_parent_billing_portal.py`
- `backend/v2/tests/application/test_webhook_handler.py`
- `backend/v2/tests/contract/test_parent_billing_customer_repo.py`
- `backend/v2/tests/contract/test_parent_payment_method_display_migration.py`
- `backend/v2/tests/interface/test_parent_activity_routes.py`
- `backend/v2/tests/unit/test_parent_composition.py`
- `frontend/app/(parent)/parent/payments/page.tsx`
- `frontend/lib/api/parent.ts`
- `frontend/lib/parent-billing-recovery-ui.node-test.mjs`

## Log

- 2026-07-01T14:04:12 main/NA: Task ledger created.
- 2026-07-01T14:05:53 main/working: Added RED tests for R6 method display labels: parent customer repo must persist label/last4, CompleteAutopaySetup must project card brand/last4 and bank name/last4, parent enrollment API/composition must expose them, and parent payments UI must render source fields.
- 2026-07-01T14:09:49 main/working: Implemented method display projection: setup completion extracts safe card brand/last4 and ACH bank name/last4 from Stripe PaymentMethod, persists optional display fields on parent_billing_customers, exposes them through parent enrollments, and renders them on parent payments.
- 2026-07-01T14:15:40 main/working: Addressed reviewer findings: moved parent_billing_customers validator update into new 0144 migration for already-applied 0142 environments, and added stale-display clearing so replacing a method without safe details unsets old label/last4 from role/default fields.
## Verification

- No verification recorded yet.
- 2026-07-01T14:05:53: RED: focused backend command for repo/setup/API/composition display-label tests failed as expected: repo did not accept payment_method_label, setup projection passed None, ParentEnrollmentView dropped fields, composition omitted fields. Frontend node static test failed as expected because parent API/page lacked autopay_payment_method_label/autopay_payment_method_last4.
- 2026-07-01T14:09:49: GREEN focused: backend RED set now passed 5 tests; broader affected backend group passed 111 tests with 1 existing Starlette/httpx warning. Touched backend ruff check/format passed. Frontend node parent billing recovery UI test passed 4 tests. pnpm typecheck passed. One earlier node invocation from frontend/ used the wrong path and failed with file-not-found; rerun from repo root passed.
- 2026-07-01T14:15:40: Review-fix verification: stale-clear + 0144 migration regressions passed 2 tests; affected backend group passed 113 tests with 1 existing Starlette/httpx warning. Touched backend ruff check/format passed after formatting 0144. Frontend node test passed 4 tests and pnpm typecheck passed.
- 2026-07-01T14:20:53: Final DoD: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1981 passed, 1 known cwd-path failure in test_bootstrap_source_does_not_reference_default_academy_id; same test passes from backend/ with PYTHONPATH=..; ruff check backend/v2 passed; ruff format --check backend/v2 passed; lint-imports backend/pyproject.toml passed; node parent billing UI test passed; frontend pnpm typecheck passed; frontend pnpm lint passed with 0 errors and 5 existing warnings.
## Reusable Lessons

- None recorded yet.
