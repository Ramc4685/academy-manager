# issue 232 monthly invoice generation recovery

## Current State

Status: active

## Problem

Monthly invoice generation must repair orphan invoice keys and header-only invoices, expose repair/failure counts, and avoid hiding partial failures as skipped_existing.

## Changed Files

- None recorded yet.

## Log

- 2026-06-21T20:31:47 main/NA: Task ledger created.
- 2026-06-21T20:33:14 main/working: Inspected issue #232, AGENTS docs, ADR-0012, active #224 ledger, monthly generation code, ledger repo, credit repo, API DTOs, and admin UI. Plan: make ledger create_invoice repair missing lines, make monthly duplicate recovery distinguish key-only/header-only/failed repair, read applied credit from account_credit_ledger source-of-truth, expose repair/failure counts, and update admin summary/warning copy.
- 2026-06-21T20:44:08 main/working: Changed files: backend/v2/contexts/billing/application/use_cases/admin_payment_ops.py; backend/v2/contexts/billing/infrastructure/mongo_billing_ledger_repo.py; backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py; backend/v2/interfaces/admin/views.py; backend/v2/tests/contract/test_mongo_payment_repo.py; backend/v2/tests/interface/test_admin_billing.py; frontend/lib/api/admin.ts; frontend/app/(admin)/admin/payments/page.tsx; test_result.md; docs/test-results/active/2026-06-21-issue-232-monthly-invoice-generation-recovery.md.
- 2026-06-22T07:08:13 main/working: Added regression coverage and recovery logic so duplicate monthly generation recognizes an existing non-deterministic invoice for the same enrollment and period as complete instead of creating inv-monthly duplicates.
## Verification

- No verification recorded yet.
- 2026-06-21T20:35:36: RED focused tests: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && pytest backend/v2/tests/contract/test_mongo_payment_repo.py::test_generate_monthly_repairs_header_without_monthly_line backend/v2/tests/contract/test_mongo_payment_repo.py::test_generate_monthly_recovers_credit_from_source_of_truth_when_audit_missing backend/v2/tests/interface/test_admin_billing.py::test_generate_monthly_payments -q => 3 failed as expected: GenerateMonthlyPaymentsResult/response lacks repaired_orphan_keys, repaired_partial_invoices, failed_repair fields.
- 2026-06-21T20:41:17: GREEN focused backend: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && pytest backend/v2/tests/contract/test_mongo_payment_repo.py backend/v2/tests/contract/test_billing_ledger_storage.py backend/v2/tests/contract/test_billing_idempotency.py backend/v2/tests/interface/test_admin_billing.py::test_generate_monthly_payments -q => 36 passed, 1 StarletteDeprecationWarning.
- 2026-06-21T20:41:18: Backend style: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && cd backend && ruff format --check touched backend files && ruff check touched backend files => passed after formatting test_mongo_payment_repo.py.
- 2026-06-21T20:41:18: Frontend checks: cd frontend && pnpm install --frozen-lockfile => passed; pnpm typecheck => passed; pnpm lint => passed with 5 existing warnings outside touched files.
- 2026-06-21T20:42:12: Final focused backend: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && cd backend && ruff format --check/check touched backend files => passed; pytest backend/v2/tests/contract/test_mongo_payment_repo.py backend/v2/tests/contract/test_billing_ledger_storage.py backend/v2/tests/contract/test_billing_idempotency.py backend/v2/tests/interface/test_admin_billing.py::test_generate_monthly_payments -q => 37 passed, 1 StarletteDeprecationWarning.
- 2026-06-21T20:43:46: Full backend v2 suite: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && cd backend && pytest v2/tests -q => 1480 passed, 5 warnings in 34.74s. Note: root-cwd variant failed one path-sensitive bootstrap source test; documented backend cwd passed.
- 2026-06-21T20:45:44: Final full backend v2 suite after concurrent regression: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && cd backend && pytest v2/tests -q => 1481 passed, 5 warnings in 33.53s.
- 2026-06-22T07:08:13: RED regression before fix: pytest backend/v2/tests/contract/test_mongo_payment_repo.py::test_generate_monthly_treats_existing_period_invoice_with_non_monthly_id_as_complete -q failed with skipped_existing=0/failed_repair=1 for prod-style invoice IDs.
- 2026-06-22T07:08:13: GREEN focused regression: same pytest target => 1 passed.
- 2026-06-22T07:08:13: Payment repo contracts: pytest backend/v2/tests/contract/test_mongo_payment_repo.py -q => 17 passed.
- 2026-06-22T07:08:14: Focused billing/admin tests: pytest backend/v2/tests/contract/test_billing_ledger_storage.py backend/v2/tests/contract/test_billing_idempotency.py backend/v2/tests/interface/test_admin_billing.py::test_generate_monthly_payments -q => 22 passed, 1 existing StarletteDeprecationWarning.
- 2026-06-22T07:08:14: Backend lint/format: ruff format --check and ruff check on touched backend files => passed.
- 2026-06-22T07:08:14: Full backend v2 suite: cd backend && pytest v2/tests -q => 1482 passed, 5 warnings.
- 2026-06-22T07:08:14: Frontend checks: pnpm typecheck => passed; pnpm lint => passed with 5 existing warnings outside touched files.
## Reusable Lessons

- None recorded yet.
