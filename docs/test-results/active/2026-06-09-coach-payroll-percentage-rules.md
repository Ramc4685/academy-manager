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
- 2026-06-27T08:00:25 main/working: Issue #251: added regression coverage for naive occurrence start against UTC-aware coach-rate timeline and normalized occurrence start to UTC before payout rate lookup/missing-rate classification.
- 2026-06-27T08:15:47 main/working: Read-only production payroll data probe: April 2026 has 0 session_occurrences for acad_blno_badminton despite 5 configured sessions, so payroll reader has no coaches/rows. May has 4 payable reader occurrences, 2 payout_periods, 4 lines. June has 13 occurrences, 12 payable reader occurrences across 2 coaches, 0 payout_periods; one coach has 2 payable June 10 occurrences before their first rate effective 2026-06-14, matching the missing-rate crash path fixed in issue #251.
## Verification

- No verification recorded yet.
- 2026-06-09T18:04:31: backend: pytest v2/tests 990 passed; ruff format+check clean. frontend: tsc clean, eslint clean, node unit tests pass. E2E skipped (no e2e changes).
- 2026-06-09T20:37:11: pytest v2/tests 992 passed (2 new contract tests for completion derivation); ruff clean
- 2026-06-18T11:01:37: RED confirmed: focused legacy percent-rate tests failed before fix with total_minor 0 and billing_unit per_session. GREEN: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_payable_occurrence_query.py v2/tests/contract/test_coach_rate_repo.py v2/tests/application/test_coach_payout.py v2/tests/application/test_manage_payout_period.py -q -> 40 passed. Interface: pytest v2/tests/interface/test_admin_payout_periods.py v2/tests/interface/test_admin_coach_pay_rates.py -q -> 9 passed, 1 Starlette/httpx deprecation warning. Backend lint: ruff format --check + ruff check on touched backend files -> clean. Frontend: cd frontend && pnpm typecheck -> passed; pnpm lint -> 0 errors, 5 existing warnings. Local smoke: scripts/local_test_stack.sh smoke -> backend and frontend health ok. Browser QA blocked on target payout route because local DB/Auth are empty and scripts/local_test_stack.sh seed is explicitly destructive, so it was not run without approval.
- 2026-06-18T11:22:01: RED confirmed: test_expected_revenue_prorates_monthly_session_fee_across_occurrences failed with {60000} expected revenue instead of {15000}. GREEN: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_payable_occurrence_query.py v2/tests/contract/test_occurrence_completion_derivation.py v2/tests/contract/test_coach_rate_repo.py v2/tests/application/test_coach_payout.py v2/tests/application/test_manage_payout_period.py -q -> 43 passed. Ruff format/check on touched backend files -> clean.
- 2026-06-27T08:01:02: Issue #251 RED: cd backend && source .venv/bin/activate && pytest v2/tests/application/test_coach_payout.py -q -k naive failed before implementation with TypeError: can't compare offset-naive and offset-aware datetimes in _missing_rate_reason.
- 2026-06-27T08:01:02: Issue #251 GREEN: cd backend && source .venv/bin/activate && pytest v2/tests/application/test_coach_payout.py -q -k naive -> 1 passed, 26 deselected.
- 2026-06-27T08:01:02: Issue #251 related payroll suite: cd backend && source .venv/bin/activate && pytest v2/tests/application/test_coach_payout.py v2/tests/application/test_list_monthly_payroll.py v2/tests/interface/test_admin_payroll_month.py -q -> 43 passed, 1 existing Starlette/httpx warning.
- 2026-06-27T08:01:02: Issue #251 lint/format: cd backend && source .venv/bin/activate && ruff format --check v2/contexts/coaching/application/use_cases/compute_payout.py v2/tests/application/test_coach_payout.py && ruff check v2/contexts/coaching/application/use_cases/compute_payout.py v2/tests/application/test_coach_payout.py -> 2 files already formatted; all checks passed.
- 2026-06-27T08:03:10: Issue #251 post-review focused regression: cd backend && source .venv/bin/activate && pytest v2/tests/application/test_coach_payout.py -q -k naive -> 1 passed, 26 deselected. Regression now also asserts UTC-aware repository lookup and missing_rate warning.
- 2026-06-27T08:03:10: Issue #251 post-review related payroll suite: cd backend && source .venv/bin/activate && pytest v2/tests/application/test_coach_payout.py v2/tests/application/test_list_monthly_payroll.py v2/tests/interface/test_admin_payroll_month.py -q -> 43 passed, 1 existing Starlette/httpx warning.
- 2026-06-27T08:03:10: Issue #251 post-review lint/format: cd backend && source .venv/bin/activate && ruff format --check v2/contexts/coaching/application/use_cases/compute_payout.py v2/tests/application/test_coach_payout.py && ruff check v2/contexts/coaching/application/use_cases/compute_payout.py v2/tests/application/test_coach_payout.py -> 2 files already formatted; all checks passed.
- 2026-06-27T08:48:58: Staging-style UI check on local BLNO seed: issue-branch backend on 127.0.0.1:8011 + frontend on localhost:3011. Browser login as seeded admin, /admin/payouts month input verified API 200 and visible rows for 2026-04, 2026-05, 2026-06. Screenshots saved: /tmp/issue251-ui-april.png, /tmp/issue251-ui-may.png, /tmp/issue251-ui-june.png.
- 2026-06-27T09:44:28: Staging-style UI generate check: clicked Generate all for 2026-06 on /admin/payouts via localhost:3011 against issue backend 8011. Browser observed GET /api/v2/admin/payroll/2026-06 200, POST /api/v2/admin/payroll/2026-06/generate 200, follow-up GET 200. UI changed from Not generated to Draft/Open for Kishore and Gowtham. Direct API persisted rows status=draft with period_id present. Screenshot: /tmp/issue251-ui-june-generated.png.
## Reusable Lessons

- None recorded yet.
