# coach payroll percentage rules

## Current State

Status: active

## Problem

Verify percentage-based coach pay, absence gating, replacement attribution, and admin pay-rate management

## Changed Files

- None recorded yet.

## Log

- 2026-06-09T18:04:31 main/NA: Task ledger created.
- 2026-06-09T18:04:31 main/working: Added percent_of_revenue coach rates, attendance gating + overrides in ComputeCoachPayout and billing derive path, expected-revenue resolver, admin pay-rate routes + UI
- 2026-06-09T20:37:11 main/working: Item 4: past non-cancelled occurrences now count as completed in both payout paths (billing derive filter + composition adapter status mapping)
- 2026-06-18T10:51:55 main/working: Investigating payout recompute zero pay for percent-of-session-fee coach rules and broken correction drawer UI.
- 2026-06-18T11:01:37 main/working: Fixed coach payout percent-rate recompute for legacy BLNO coach_rates fields, corrected payout period rate labeling, changed draft row status to Calculated, and made the occurrence correction drawer opaque/readable.
- 2026-06-18T11:19:44 main/working: Investigating expected revenue basis: monthly session fees are being applied per occurrence instead of prorated across occurrences in the payout month.
- 2026-06-18T11:22:01 main/working: Corrected expected revenue basis for payout recompute: monthly session amount is prorated across non-cancelled payable occurrences in the payout period before applying active enrollment count and coach percentage.
## Verification

- No verification recorded yet.
- 2026-06-09T18:04:31: backend: pytest v2/tests 990 passed; ruff format+check clean. frontend: tsc clean, eslint clean, node unit tests pass. E2E skipped (no e2e changes).
- 2026-06-09T20:37:11: pytest v2/tests 992 passed (2 new contract tests for completion derivation); ruff clean
- 2026-06-18T11:01:37: RED confirmed: focused legacy percent-rate tests failed before fix with total_minor 0 and billing_unit per_session. GREEN: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_payable_occurrence_query.py v2/tests/contract/test_coach_rate_repo.py v2/tests/application/test_coach_payout.py v2/tests/application/test_manage_payout_period.py -q -> 40 passed. Interface: pytest v2/tests/interface/test_admin_payout_periods.py v2/tests/interface/test_admin_coach_pay_rates.py -q -> 9 passed, 1 Starlette/httpx deprecation warning. Backend lint: ruff format --check + ruff check on touched backend files -> clean. Frontend: cd frontend && pnpm typecheck -> passed; pnpm lint -> 0 errors, 5 existing warnings. Local smoke: scripts/local_test_stack.sh smoke -> backend and frontend health ok. Browser QA blocked on target payout route because local DB/Auth are empty and scripts/local_test_stack.sh seed is explicitly destructive, so it was not run without approval.
- 2026-06-18T11:22:01: RED confirmed: test_expected_revenue_prorates_monthly_session_fee_across_occurrences failed with {60000} expected revenue instead of {15000}. GREEN: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_payable_occurrence_query.py v2/tests/contract/test_occurrence_completion_derivation.py v2/tests/contract/test_coach_rate_repo.py v2/tests/application/test_coach_payout.py v2/tests/application/test_manage_payout_period.py -q -> 43 passed. Ruff format/check on touched backend files -> clean.
## Reusable Lessons

- None recorded yet.
