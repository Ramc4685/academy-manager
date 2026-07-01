# autopay slice g ach lifecycle

## Current State

Status: active

## Problem

ACH processing lifecycle, returns/reversal markers, microdeposit verification window, and card fallback model

## Changed Files

- None recorded yet.

## Log

- 2026-07-01T11:26:14 main/NA: Task ledger created.
- 2026-07-01T11:26:21 main/working: Slice G worktree created at .worktrees/slice-g from main e31f90e5; migration 0142 assigned for ACH lifecycle/card-fallback schema if needed; implementer dispatch pending.
- 2026-07-01T11:31:19 main/working: Read project/backend/testing/event rules, Slice G plan, parent-checkout ACH requirements from parent checkout because the requested requirements file is missing in this worktree, and inspected autopay charge, webhook, setup, parent customer, ledger, migrations, and Stripe fixture patterns. Starting RED tests for ACH processing/returns/microdeposit/fallback model.
- 2026-07-01T11:44:06 main/working: Implemented Slice G ACH processing/settlement/return handling, microdeposit pending setup, primary/fallback payment method projection, migration 0142, and ACH Stripe fixture replay coverage.
- 2026-07-01T11:46:20 main/working: DoD: RED recorded for missing ACH helper and behavior gaps; GREEN focused tests, fixture replay, affected billing tests, required static checks, and full backend/v2 pytest run completed with only the allowed bootstrap cwd-path failure.
## Verification

- No verification recorded yet.
- 2026-07-01T11:33:32: RED: focused pytest for ACH return codes/processing/returns/microdeposit/migration failed at collection with ModuleNotFoundError for backend.v2.contexts.billing.domain.ach_returns, confirming the return-code helper is missing before implementation.
- 2026-07-01T11:40:51: GREEN focused: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_ach_return_codes.py backend/v2/tests/unit/test_charge_autopay_use_case.py::test_ach_processing_records_pending_attempt_without_allocation backend/v2/tests/application/test_webhook_handler.py::test_autopay_ach_payment_intent_processing_records_pending_attempt_only backend/v2/tests/application/test_webhook_handler.py::test_autopay_ach_processing_cross_tenant_invoice_is_quarantined backend/v2/tests/application/test_webhook_handler.py::test_autopay_ach_return_after_paid_reopens_invoice_and_records_return_code backend/v2/tests/application/test_webhook_handler.py::test_ach_setup_requiring_microdeposit_verification_does_not_mark_active backend/v2/tests/application/test_webhook_handler.py::test_card_setup_can_be_stored_as_fallback_and_active_immediately backend/v2/tests/contract/test_ach_lifecycle_migration.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py -q => 26 passed.
- 2026-07-01T11:44:06: Required pytest: source backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests -q => 1921 passed, 1 known allowed bootstrap cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id.
- 2026-07-01T11:44:06: Required static checks: ruff check backend/v2 && ruff format --check backend/v2 && lint-imports --config backend/pyproject.toml => all passed; import-linter 4 contracts kept.
- 2026-07-01T11:46:13: Final affected checks after idempotency tweak: focused billing files => 139 passed; ruff check backend/v2, ruff format --check backend/v2, lint-imports --config backend/pyproject.toml => all passed.
- 2026-07-01T11:46:13: Final required pytest after all changes: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1921 passed, 1 known allowed bootstrap cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id.
## Reusable Lessons

- None recorded yet.
