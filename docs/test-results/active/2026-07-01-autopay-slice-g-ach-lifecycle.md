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
- 2026-07-01T11:58:07 main/working: Rework implemented: reversal replay converges after preinserted reversal row, fallback-only active method no longer marks enrollment active/default, ACH return classification ignores metadata/free-text, webhook ledger port typed as LedgerRepository, and Stripe-shaped return-code traversal moved to application layer.
- 2026-07-01T12:02:14 main/done: Slice G scoped rework DoD complete: replay convergence, fallback-only activation guard, ACH return classification tightening, LedgerRepository port typing, and provider-neutral Nacha domain normalization are implemented and verified.
- 2026-07-01T12:15:59 main/done: Second scoped rework complete: partial ACH returns are explicitly unsupported without projection changes, ACH classification no longer trusts event metadata-only bank hints, charge-path ACH metadata has server-derived provenance, and duplicate full-return alternate event shapes no longer emit duplicate PaymentRefunded events.
- 2026-07-01T12:16:20 main/done: Documented scope: partial amount-aware ACH reversal remains deferred beyond Slice G; this pass records unsupported partial returns without changing invoice/payment/allocation projections.
- 2026-07-01T12:26:24 main/working: Post-rebase reviewer rework: pending primary ACH now updates primary projection only and does not overwrite chargeable default fields; added real Mongo repository contract coverage.
- 2026-07-01T12:29:58 main/working: Post-review ordering rework: autopay setup now persists consent/projection before calling Stripe to set the customer default, then activates enrollment only after Stripe succeeds.
## Verification

- No verification recorded yet.
- 2026-07-01T11:33:32: RED: focused pytest for ACH return codes/processing/returns/microdeposit/migration failed at collection with ModuleNotFoundError for backend.v2.contexts.billing.domain.ach_returns, confirming the return-code helper is missing before implementation.
- 2026-07-01T11:40:51: GREEN focused: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_ach_return_codes.py backend/v2/tests/unit/test_charge_autopay_use_case.py::test_ach_processing_records_pending_attempt_without_allocation backend/v2/tests/application/test_webhook_handler.py::test_autopay_ach_payment_intent_processing_records_pending_attempt_only backend/v2/tests/application/test_webhook_handler.py::test_autopay_ach_processing_cross_tenant_invoice_is_quarantined backend/v2/tests/application/test_webhook_handler.py::test_autopay_ach_return_after_paid_reopens_invoice_and_records_return_code backend/v2/tests/application/test_webhook_handler.py::test_ach_setup_requiring_microdeposit_verification_does_not_mark_active backend/v2/tests/application/test_webhook_handler.py::test_card_setup_can_be_stored_as_fallback_and_active_immediately backend/v2/tests/contract/test_ach_lifecycle_migration.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py -q => 26 passed.
- 2026-07-01T11:44:06: Required pytest: source backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests -q => 1921 passed, 1 known allowed bootstrap cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id.
- 2026-07-01T11:44:06: Required static checks: ruff check backend/v2 && ruff format --check backend/v2 && lint-imports --config backend/pyproject.toml => all passed; import-linter 4 contracts kept.
- 2026-07-01T11:46:13: Final affected checks after idempotency tweak: focused billing files => 139 passed; ruff check backend/v2, ruff format --check backend/v2, lint-imports --config backend/pyproject.toml => all passed.
- 2026-07-01T11:46:13: Final required pytest after all changes: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1921 passed, 1 known allowed bootstrap cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id.
- 2026-07-01T11:56:21: RED rework: focused Slice G pytest failed at collection because provider-neutral Nacha helpers (nacha_return_code_for_provider_failure / normalize_nacha_return_code) do not exist yet after moving Stripe-shaped traversal out of domain.
- 2026-07-01T11:58:07: RED rework behavior: focused pytest exposed review gaps after RED tests were added (provider-neutral Nacha helper missing; then reversal replay/fallback-only activation/metadata-only ACH return classification covered by new tests).
- 2026-07-01T11:58:07: GREEN rework focused: PYTHONPATH=. python -m pytest backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/application/test_parent_billing_portal.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py backend/v2/tests/contract/test_ach_lifecycle_migration.py backend/v2/tests/unit/test_ach_return_codes.py backend/v2/tests/unit/test_charge_autopay_use_case.py -q => 125 passed before warning cleanup.
- 2026-07-01T12:02:10: GREEN rework focused final: PYTHONPATH=. python -m pytest backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/application/test_parent_billing_portal.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py backend/v2/tests/contract/test_ach_lifecycle_migration.py backend/v2/tests/unit/test_ach_return_codes.py backend/v2/tests/unit/test_charge_autopay_use_case.py -q => 125 passed.
- 2026-07-01T12:02:10: DoD rework full pytest: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1924 passed, 1 known allowed bootstrap cwd-path FileNotFoundError, 5 warnings.
- 2026-07-01T12:02:10: DoD rework static: ruff check backend/v2 && ruff format --check backend/v2 && lint-imports --config backend/pyproject.toml => passed; Import Linter 4 contracts kept.
- 2026-07-01T12:10:33: RED second rework: focused pytest failed as expected with 4 behavior failures: alternate ACH return replay emitted duplicate PaymentRefunded, partial ACH return below the original payment amount over-reversed the invoice/allocation, and metadata-only ACH classification reopened invoices for charge.refunded and payment_intent.payment_failed.
- 2026-07-01T12:12:43: GREEN second rework focused: PYTHONPATH=. python -m pytest backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py backend/v2/tests/unit/test_ach_return_codes.py -q => 78 passed.
- 2026-07-01T12:13:48: GREEN second rework focused plus affected charge path: PYTHONPATH=. python -m pytest backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py backend/v2/tests/unit/test_ach_return_codes.py backend/v2/tests/unit/test_charge_autopay_use_case.py -q => 115 passed.
- 2026-07-01T12:14:39: DoD second rework full pytest: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1927 passed, 1 known allowed bootstrap cwd-path FileNotFoundError, 5 warnings.
- 2026-07-01T12:15:54: GREEN second rework post-format focused: PYTHONPATH=. python -m pytest backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py backend/v2/tests/unit/test_ach_return_codes.py backend/v2/tests/unit/test_charge_autopay_use_case.py -q => 115 passed.
- 2026-07-01T12:15:54: DoD second rework post-format full pytest: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1927 passed, 1 known allowed bootstrap cwd-path FileNotFoundError, 5 warnings.
- 2026-07-01T12:15:54: DoD second rework static: ruff check backend/v2 && ruff format --check backend/v2 && lint-imports --config backend/pyproject.toml => passed; Import Linter 4 contracts kept.
- 2026-07-01T12:26:24: Post-rebase focused G/F integration: PYTHONPATH=. python -m pytest backend/v2/tests/contract/test_parent_billing_customer_repo.py backend/v2/tests/application/test_parent_billing_portal.py backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/contract/test_ach_lifecycle_migration.py backend/v2/tests/unit/test_charge_autopay_use_case.py -q => 123 passed.
- 2026-07-01T12:27:31: Independent orchestrator DoD after rebase onto Slice F: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1945 passed, 1 known allowed bootstrap cwd-path FileNotFoundError, 5 warnings. Static checks: ruff check backend/v2 => passed; ruff format --check backend/v2 => 748 files already formatted; lint-imports --config backend/pyproject.toml => 4 contracts kept.
- 2026-07-01T12:29:58: Ordering rework focused setup tests: PYTHONPATH=. python -m pytest backend/v2/tests/application/test_parent_billing_portal.py backend/v2/tests/application/test_webhook_handler.py::test_autopay_setup_checkout_and_setup_intent_replay_do_not_duplicate_consent_event backend/v2/tests/application/test_webhook_handler.py::test_setup_intent_succeeded_completes_autopay_from_setup_metadata backend/v2/tests/application/test_webhook_handler.py::test_ach_setup_requiring_microdeposit_verification_does_not_mark_active backend/v2/tests/application/test_webhook_handler.py::test_active_fallback_card_setup_does_not_mark_enrollment_active_or_default -q => 24 passed.
- 2026-07-01T12:31:37: Independent orchestrator DoD after final ordering rework: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1946 passed, 1 known allowed bootstrap cwd-path FileNotFoundError, 5 warnings. Static checks after formatting: ruff check backend/v2 && ruff format --check backend/v2 && lint-imports --config backend/pyproject.toml => passed, 748 files formatted, 4 contracts kept. Focused ordering regression: 2 passed.
## Reusable Lessons

- None recorded yet.
