# autopay slice i connect fund flow

## Current State

Status: active

## Problem

Wire the existing Stripe Connect foundation into parent autopay setup and off-session invoice charges so ready connected accounts receive fund flow and missing/unready accounts fail closed instead of platform-charging.

## Changed Files

- `backend/v2/contexts/billing/application/use_cases/parent_billing.py`
- `backend/v2/contexts/billing/application/use_cases/charge_invoice_via_autopay.py`
- `backend/v2/contexts/billing/application/use_cases/enroll_child_in_session_type.py`
- `backend/v2/contexts/billing/application/use_cases/process_dunning_retries.py`
- `backend/v2/composition/parent.py`
- `backend/v2/composition/admin.py`
- `backend/v2/tests/application/test_dunning_worker.py`
- `backend/v2/tests/application/test_enroll_child_in_session_type.py`
- `backend/v2/tests/application/test_parent_billing_portal.py`
- `backend/v2/tests/contract/test_connect_composition_wiring.py`
- `backend/v2/tests/unit/test_charge_autopay_use_case.py`

## Log

- 2026-07-01T14:25:36 main/NA: Task ledger created.
- 2026-07-01T14:25:41 main/working: RED for fund-flow wiring: added focused tests proving parent setup Checkout and ChargeInvoiceViaAutopay must resolve a ready connected account and fail closed without one. Focused run failed as expected: StartSubscriptionCheckout and ChargeInvoiceViaAutopay do not accept connected_accounts yet.
- 2026-07-01T14:28:03 main/working: Expanded RED coverage after read-only sidecar audit found EnrollChildInSessionType also creates setup Checkout without Connect. Six focused tests now cover parent setup, enroll-child setup, and off-session charge; current failure is the expected missing connected_accounts constructor on EnrollChildInSessionType.
- 2026-07-01T14:28:59 main/working: GREEN focused: parent setup Checkout, enroll-child setup Checkout, and ChargeInvoiceViaAutopay now route ready connected accounts into Stripe calls and fail closed without ready accounts; 6 focused tests passed.
- 2026-07-01T14:36:43 main/working: Addressed review finding: dunning now parks connected_account_not_ready as a technical/config failure instead of counting a parent dunning failure, sending notice, or disabling autopay. RED regression failed before the fix; dunning worker tests now pass.
- 2026-07-01T14:38:55 reviewer/approved: Re-review found no blocking money-path issues after connected_account_not_ready dunning fix. Remaining compose_admin direct coverage was noted as hardening, not a blocker.
## Verification

- No verification recorded yet.
- 2026-07-01T14:31:47: Focused GREEN: PYTHONPATH=. python -m pytest backend/v2/tests/application/test_parent_billing_portal.py backend/v2/tests/application/test_enroll_child_in_session_type.py backend/v2/tests/unit/test_charge_autopay_use_case.py backend/v2/tests/contract/test_connect_composition_wiring.py -q => 79 passed. Touched-file ruff check passed; touched-file ruff format --check passed.
- 2026-07-01T14:33:18: Focused regression after stale-checkout edge: PYTHONPATH=. python -m pytest backend/v2/tests/application/test_parent_billing_portal.py backend/v2/tests/application/test_enroll_child_in_session_type.py backend/v2/tests/unit/test_charge_autopay_use_case.py backend/v2/tests/contract/test_connect_composition_wiring.py -q => 80 passed. Touched-file ruff check passed; touched-file ruff format --check passed.
- 2026-07-01T14:35:07: Broad backend DoD: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1989 passed, 1 known cwd-path failure in test_bootstrap_source_does_not_reference_default_academy_id; same test from backend/ with PYTHONPATH=.. passed. ruff check backend/v2 passed. ruff format --check backend/v2 passed. lint-imports --config backend/pyproject.toml passed.
- 2026-07-01T14:38:21: Final backend DoD after review fix: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1990 passed, 1 known cwd-path failure in test_bootstrap_source_does_not_reference_default_academy_id; same test from backend/ with PYTHONPATH=.. passed. ruff check backend/v2 passed. ruff format --check backend/v2 passed. lint-imports --config backend/pyproject.toml passed. Expanded affected set including dunning worker => 86 passed.
## Reusable Lessons

- None recorded yet.
