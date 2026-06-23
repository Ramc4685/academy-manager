# issue 230 coach payroll rate windows

## Current State

Status: active

## Problem

Verify coach pay-rate timeline diagnostics, unpaid occurrence reasons, repair workflow, approval guardrails, and admin warning visibility for GitHub issue #230.

## Changed Files

- None recorded yet.

## Log

- 2026-06-22T07:45:06 main/NA: Task ledger created.

## Verification

- No verification recorded yet.
- 2026-06-22T07:55:01: RED/GREEN focused backend application tests: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_manage_coach_rates.py v2/tests/application/test_coach_payout.py v2/tests/application/test_payout_period.py v2/tests/application/test_manage_payout_period.py v2/tests/application/test_list_monthly_payroll.py -q -> 71 passed.
- 2026-06-22T08:04:23: Focused backend suite: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_manage_coach_rates.py v2/tests/contract/test_coach_rate_repo.py v2/tests/application/test_coach_payout.py v2/tests/application/test_payout_period.py v2/tests/application/test_manage_payout_period.py v2/tests/application/test_list_monthly_payroll.py v2/tests/interface/test_admin_coach_pay_rates.py v2/tests/interface/test_admin_payout_periods.py v2/tests/interface/test_admin_payroll_month.py -q -> 96 passed, 1 existing Starlette/httpx warning. Backend ruff format --check v2 and ruff check v2 passed. Frontend: node node_modules/vitest/vitest.mjs run lib/payroll-warnings.test.ts lib/api/v2/payroll.test.ts lib/api/v2/payouts.test.ts -> 3 files/8 tests passed; node node_modules/typescript/bin/tsc --noEmit passed; targeted eslint on changed frontend files passed.
## Reusable Lessons

- None recorded yet.
