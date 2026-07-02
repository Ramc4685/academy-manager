# autopay slice c idempotency

## Current State

Status: active

## Problem

Cycle/amount-scoped autopay idempotency key so Stripe does not replay stale invoice amounts and true replays still dedupe

## Changed Files

- `backend/v2/contexts/billing/application/use_cases/charge_invoice_via_autopay.py`
- `backend/v2/tests/unit/test_charge_autopay_use_case.py`
- `docs/test-results/active/2026-07-01-autopay-slice-c-idempotency.md`
- `test_result.md`

## Log

- 2026-07-01T10:26:31 main/NA: Task ledger created.
- 2026-07-01T10:27:11 main/working: Slice C worktree created at .worktrees/slice-c from 6c33b474; implementer agent dispatched for TDD idempotency-key change. Scope: no migration expected; charge path only.
- 2026-07-01T10:28:56 main/working: Slice C kickoff: read TDD/backend/testing/feedback guidance, active ledger, plan, charge use case, and unit tests; adding focused RED tests for period/amount-scoped idempotency.
- 2026-07-01T10:32:49 main/working: Implemented Slice C after RED: PI idempotency key now uses invoice_id, period, and balance_due_cents from the fresh invoice; payment-attempt keys include invoice_id, period, amount, status, and PI-or-stripe-error suffix. Ledger payment/allocation PI keys unchanged.
## Verification

- 2026-07-01T10:32:55: RED: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate; PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_charge_autopay_use_case.py -q -k 'idempotency_key or stripe_exception_failed_attempt_key' failed as expected: old PI keys were autopay-{invoice_id}, and old stripe-error attempt key lacked period/amount/status scope.
- 2026-07-01T10:32:59: GREEN focused: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate; PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_charge_autopay_use_case.py -q passed: 26 passed in 0.20s.
- 2026-07-01T10:33:05: DoD: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate; PYTHONPATH=. python -m pytest backend/v2/tests -q completed with known allowed failure test_bootstrap_source_does_not_reference_default_academy_id cwd-path FileNotFoundError; result 1 failed, 1883 passed, 5 warnings in 116.62s. ruff check backend/v2 passed. ruff format --check backend/v2 passed (736 files already formatted). lint-imports --config backend/pyproject.toml passed (4 contracts kept).
- 2026-07-01T10:43:01: Independent orchestrator DoD: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests -q => 1883 passed / 1 known unrelated failure test_bootstrap_source_does_not_reference_default_academy_id (cwd-path FileNotFoundError), 5 warnings. ruff check backend/v2 => passed. ruff format --check backend/v2 => 736 files already formatted. lint-imports --config backend/pyproject.toml => 4 contracts kept, 0 broken. Reviewer trio re-run against committed diff a8659b7e: no findings.
## Reusable Lessons

- None recorded yet.
