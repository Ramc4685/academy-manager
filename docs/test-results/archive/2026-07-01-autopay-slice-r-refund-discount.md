# autopay slice r refund discount

## Current State

Status: complete

## Problem

Slice R refund ledger contract: full refunds should reverse ACH cash-discount lines proportionally; partial refunds leave the discount untouched; preserve idempotency and paid-invoice ledger explainability.

## Changed Files

- `backend/v2/contexts/billing/infrastructure/mongo_billing_ledger_repo.py`
- `backend/v2/tests/contract/test_billing_ledger_storage.py`
- `docs/test-results/archive/2026-07-01-autopay-slice-r-refund-discount.md`

## Log

- 2026-07-01T13:29:01 main/NA: Task ledger created.
- 2026-07-01T13:30:13 main/working: Recovered requirements review from shared checkout untracked docs/requirements/2026-06-30-autopay-ach-card-fee-requirements-review-v2.md; current slice target is the Slice E/ledger-plan refund follow-up: full refunds reverse ACH cash-discount evidence, partial refunds leave discount untouched. Added RED contract tests in test_billing_ledger_storage.py.
- 2026-07-01T13:33:17 main/working: Implemented ACH discount reversal audit rows for full invoice refunds in MongoBillingLedgerRepository; partial refunds still leave discount lines untouched.
- 2026-07-01T13:41:30 main/working: Addressed code-review money-path risks: apply_invoice_refund now compensates if ACH discount reversal row creation fails; reverse_invoice_refund bumps invoice version; reversal cleanup is version-scoped to avoid deleting newer full-refund artifacts; non-negative ach_discount rows are ignored.
## Verification

- 2026-07-01T13:30:13: RED: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests/contract/test_billing_ledger_storage.py::test_partial_invoice_refund_leaves_ach_discount_unreversed backend/v2/tests/contract/test_billing_ledger_storage.py::test_full_invoice_refund_records_ach_discount_reversal_credit_note -q => 1 passed, 1 failed as expected; full-refund failure because no ACH_DISCOUNT_REVERSAL credit-note row exists.
- 2026-07-01T13:32:45: GREEN: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests/contract/test_billing_ledger_storage.py::test_partial_invoice_refund_leaves_ach_discount_unreversed backend/v2/tests/contract/test_billing_ledger_storage.py::test_full_invoice_refund_records_ach_discount_reversal_credit_note -q => 2 passed in 0.29s
- 2026-07-01T13:42:30: Focused GREEN after review fixes: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests/contract/test_billing_ledger_storage.py backend/v2/tests/contract/test_admin_billing_idempotency.py -q => 26 passed in 0.67s; ruff check touched repo/test files => passed; ruff format --check touched repo/test files => passed.
- 2026-07-01T13:42:30: Full backend DoD: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests -q => 1974 passed, 1 failed: known cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id; confirmed source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && PYTHONPATH=.. python -m pytest v2/tests/application/test_bootstrap_academy.py::test_bootstrap_source_does_not_reference_default_academy_id -q from backend/ => 1 passed.
- 2026-07-01T13:42:30: Full backend quality checks: ruff check backend/v2 => passed; ruff format --check backend/v2 => 755 files already formatted; lint-imports --config backend/pyproject.toml => 4 contracts kept, 0 broken.

## Reusable Lessons

- None recorded yet.
