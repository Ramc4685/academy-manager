# autopay slice e cash discount

## Current State

Status: active

## Problem

ACH cash-discount fee model: ACH earns disclosed discount line before autopay idempotency key, card/unknown fail-safe to no discount

## Changed Files

- None recorded yet.

## Log

- 2026-07-01T10:44:31 main/NA: Task ledger created.
- 2026-07-01T10:45:23 main/working: Slice E worktree created at .worktrees/slice-e from main 15019fc8; implementer agent dispatched for TDD cash-discount model. Migration 0140 reserved only if metadata/schema change is needed.
- 2026-07-01T10:46:07 main/working: Starting Slice E implementation in .worktrees/slice-e; reading required billing rules/source before RED tests.
- 2026-07-01T10:53:45 main/working: Implemented ACH cash discount domain calculation, autopay discount line/idempotency ordering, PaymentMethod funding lookup, LedgerPayment metadata with migration 0140, and admin composition settings wiring. Refund discount-line reversal deferred: current refund paths span composition, Stripe refund execution, webhook replay, and ledger projections; cash-discount reversal rule needs explicit ledger contract.
## Verification

- No verification recorded yet.
- 2026-07-01T10:49:14: RED: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_billing_fees.py backend/v2/tests/unit/test_charge_autopay_use_case.py backend/v2/tests/contract/test_billing_ledger_storage.py -q failed as expected: missing domain.fees. Separate REDs: test_charge_autopay_use_case failed on ChargeInvoiceViaAutopay unexpected settings kwarg; test_record_payment_round_trips_metadata failed with KeyError metadata.
- 2026-07-01T10:51:36: GREEN focused: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_billing_fees.py backend/v2/tests/unit/test_charge_autopay_use_case.py backend/v2/tests/contract/test_billing_ledger_storage.py -q passed (63 passed).
- 2026-07-01T10:53:25: DoD pytest: PYTHONPATH=. python -m pytest backend/v2/tests -q -> 1902 passed, 1 known allowed cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id.
- 2026-07-01T10:53:45: DoD lint: ruff check backend/v2 passed; ruff format --check backend/v2 passed; lint-imports --config backend/pyproject.toml passed (4 contracts kept).
## Reusable Lessons

- None recorded yet.
