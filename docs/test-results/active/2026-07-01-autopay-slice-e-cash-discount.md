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
- 2026-07-01T11:05:39 main/working: Rework pass fixed reviewer findings: stale existing ACH discount lines are removed/restored before PI amount/key when current funding/settings are ineligible; webhook-wins autopay success now records disclosure/discount metadata; migration 0140 validator preserves existing status enum and money type contract. Refund rule durably tracked: full refund should reverse discount line proportionally; partial refund leaves discount untouched; implementation deferred to Slice R/refund ledger contract.
- 2026-07-01T11:20:37 main/working: Scoped rework added RED regression for existing ACH discount line with changed current ACH settings, then reconciled deterministic discount line before PI amount/key and LedgerPayment metadata.
## Verification

- No verification recorded yet.
- 2026-07-01T10:49:14: RED: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_billing_fees.py backend/v2/tests/unit/test_charge_autopay_use_case.py backend/v2/tests/contract/test_billing_ledger_storage.py -q failed as expected: missing domain.fees. Separate REDs: test_charge_autopay_use_case failed on ChargeInvoiceViaAutopay unexpected settings kwarg; test_record_payment_round_trips_metadata failed with KeyError metadata.
- 2026-07-01T10:51:36: GREEN focused: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_billing_fees.py backend/v2/tests/unit/test_charge_autopay_use_case.py backend/v2/tests/contract/test_billing_ledger_storage.py -q passed (63 passed).
- 2026-07-01T10:53:25: DoD pytest: PYTHONPATH=. python -m pytest backend/v2/tests -q -> 1902 passed, 1 known allowed cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id.
- 2026-07-01T10:53:45: DoD lint: ruff check backend/v2 passed; ruff format --check backend/v2 passed; lint-imports --config backend/pyproject.toml passed (4 contracts kept).
- 2026-07-01T11:02:54: REWORK RED: focused regression command failed as expected: existing ach_discount line persisted for current card/retrieve-fail/disabled settings; webhook autopay PI success recorded LedgerPayment.metadata=None; migration 0140 status validator was arbitrary string. True ACH replay non-duplication test in same command passed.
- 2026-07-01T11:05:39: REWORK GREEN focused: stale-discount card/retrieve-fail/settings-disabled regressions, true ACH replay, webhook-wins metadata, and 0140 validator contract command passed (6 passed).
- 2026-07-01T11:06:51: REWORK focused broader: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_charge_autopay_use_case.py backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/contract/test_migrations_legacy_compat.py -q passed (97 passed).
- 2026-07-01T11:06:51: REWORK DoD: PYTHONPATH=. python -m pytest backend/v2/tests -q -> 1907 passed, 1 known allowed cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id; ruff check backend/v2 passed; ruff format --check backend/v2 passed; lint-imports --config backend/pyproject.toml passed (4 contracts kept).
- 2026-07-01T11:09:02: REWORK final DoD rerun after validator minimization: PYTHONPATH=. python -m pytest backend/v2/tests -q -> 1907 passed, 1 known allowed cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id; ruff check backend/v2 passed; ruff format --check backend/v2 passed; lint-imports --config backend/pyproject.toml passed (4 contracts kept).
- 2026-07-01T11:20:37: SCOPED RED: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_charge_autopay_use_case.py::test_existing_ach_discount_is_reconciled_when_current_settings_change -q failed as expected on stale existing line description (old ACH autopay savings retained).
- 2026-07-01T11:20:37: SCOPED GREEN focused: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_charge_autopay_use_case.py::test_existing_ach_discount_is_reconciled_when_current_settings_change -q passed (1 passed); PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_charge_autopay_use_case.py -q passed (36 passed).
- 2026-07-01T11:21:31: SCOPED REWORK DoD: PYTHONPATH=. python -m pytest backend/v2/tests -q -> 1908 passed, 1 known allowed cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id; ruff check backend/v2 passed; ruff format --check backend/v2 passed; lint-imports --config backend/pyproject.toml passed (4 contracts kept).
- 2026-07-01T11:22:39: SCOPED REWORK final rerun after cleanup: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_charge_autopay_use_case.py -q passed (36 passed); PYTHONPATH=. python -m pytest backend/v2/tests -q -> 1908 passed, 1 known allowed cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id; ruff check backend/v2 passed; ruff format --check backend/v2 passed; lint-imports --config backend/pyproject.toml passed (4 contracts kept).
## Reusable Lessons

- None recorded yet.
