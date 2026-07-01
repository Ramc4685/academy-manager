# autopay slice j fee policy

## Current State

Status: archived

## Problem

Verify cash-discount fee policy, saved card debit/prepaid fail-safe behavior, and refund discount handling after Slice I.

## Changed Files

- `backend/v2/tests/unit/test_charge_autopay_use_case.py`

## Log

- 2026-07-01T14:43:34 main/NA: Task ledger created.
- 2026-07-01T14:44:34 main/working: Added autopay unit coverage proving saved card credit/debit/prepaid funding charges the full invoice balance, creates no fee/discount invoice line, and sends no fee/discount metadata.
- 2026-07-01T14:45:19 explorer/passed: Read-only sidecar audit found cash-discount-only is implemented, no processing_fee/payment_method_fee implementation exists, ACH refund discount behavior is covered, and the remaining smallest gap is explicit no-card-fee regression coverage.
## Verification

- No verification recorded yet.
- 2026-07-01T14:44:44: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_charge_autopay_use_case.py -q -> 43 passed
- 2026-07-01T14:44:44: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_billing_fees.py backend/v2/tests/contract/test_billing_ledger_storage.py -q -> 36 passed
- 2026-07-01T14:45:26: ruff check backend/v2/tests/unit/test_charge_autopay_use_case.py && ruff format --check backend/v2/tests/unit/test_charge_autopay_use_case.py -> passed
## Reusable Lessons

- None recorded yet.
