# issue-227-paid-at-revenue

## Current State

Status: active

## Problem

Reports bucket collected revenue by row creation time instead of payment-effective paid_at; verify dashboard, P&L, finance revenue, CSV export, legacy fallback, Stripe paid_at semantics, refunds, month boundaries, de-dupe, and tenant scoping.

## Changed Files

- None recorded yet.

## Log

- 2026-06-21T19:38:09 main/NA: Task ledger created.
- 2026-06-21T19:38:39 main/working: Started issue #227 on branch feat/issue-227-paid-at-revenue based on issue #224 branch; created ledger and dispatched explorers for reporting paths and Stripe paid_at paths.
- 2026-06-21T19:43:23 main/working: Implementation plan created at docs/plans/2026-06-21-issue-227-paid-at-revenue.md. Baseline focused tests are green. Worker subagent dispatched for paid_at/effective-date reporting implementation.
- 2026-06-21T19:45:37 main/working: Started Task 1 implementation in issue-227 worktree; reading admin reporting and billing finance paths before edits.
- 2026-06-21T19:53:36 main/working: Implemented Task 1: effective payment date helpers, paid_at-based dashboard ledger cash, legacy effective-date filtering, paid_at in recent ledger rows, effective-date revenue CSV, and ledger-aware admin finance revenue query with legacy de-dupe and refund netting.
- 2026-06-21T19:58:39 main/working: Spec compliance review follow-up: fixing ledger-specific date precedence, legacy CSV effective dates, and allocation/invoice-id CSV de-dupe gaps only.
- 2026-06-21T20:04:29 main/working: Spec re-review CSV follow-up: fixing revenue CSV so allocated ledger payments suppressed from list_payments_recent are still counted by ledger effective date exactly once.
- 2026-06-21T20:11:39 main/working: Code-quality review follow-up: splitting legacy dashboard cash effective-date handling from period-based collections risk, tightening revenue query projections, and loosening revenue_query typing.
- 2026-06-21T20:17:18 main/working: Quality re-review scaling follow-up: reducing _AdminEffectiveRevenueQuery row-by-row revenue processing with Mongo aggregation-backed monthly grouping and retained projected key pass for legacy de-dupe.
- 2026-06-21T20:22:47 main/working: Quality follow-up: replacing unbounded allocation  and legacy  de-dupe with batched allocation lookup plus batched duplicate legacy revenue subtraction.
## Verification

- No verification recorded yet.
- 2026-06-21T19:41:12: Baseline before #227 code changes: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 63 passed, 1 Starlette/httpx deprecation warning.
- 2026-06-21T19:52:50: Style verification after Task 1 implementation: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff format --check v2 => 665 files already formatted; /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff check v2 => All checks passed.
- 2026-06-21T19:52:50: Focused backend verification after Task 1 implementation: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 67 passed, 1 existing Starlette/httpx deprecation warning.
- 2026-06-21T19:53:27: Post-review rerun after UTC normalization: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 67 passed, 1 existing Starlette/httpx deprecation warning; ruff format --check v2 => 665 files already formatted; ruff check v2 => All checks passed.
- 2026-06-21T19:54:59: Post-implementation focused tests: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 67 passed, 1 Starlette/httpx deprecation warning.
- 2026-06-21T20:01:43: Spec compliance follow-up verification: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 69 passed, 1 existing Starlette/httpx deprecation warning; ruff format --check v2 => 665 files already formatted; ruff check v2 => All checks passed.
- 2026-06-21T20:02:27: Post-spec-fix focused tests: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 69 passed, 1 Starlette/httpx deprecation warning.
- 2026-06-21T20:05:20: CSV re-review follow-up verification: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 70 passed, 1 existing Starlette/httpx deprecation warning; ruff format --check v2 => 665 files already formatted; ruff check v2 => All checks passed.
- 2026-06-21T20:05:54: Final focused backend verification: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 70 passed, 1 Starlette/httpx deprecation warning; /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff format --check v2 => 665 files already formatted; /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff check v2 => All checks passed.
- 2026-06-21T20:14:34: Code-quality follow-up verification: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 70 passed, 1 existing Starlette/httpx deprecation warning; ruff format --check v2 => 665 files already formatted; ruff check v2 => All checks passed.
- 2026-06-21T20:15:05: Post-code-quality-fix verification: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 70 passed, 1 Starlette/httpx deprecation warning; ruff format --check v2 => 665 files already formatted; ruff check v2 => All checks passed.
- 2026-06-21T20:20:39: Revenue query scaling follow-up verification: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 70 passed, 1 existing Starlette/httpx deprecation warning; ruff format --check v2 => 665 files already formatted; ruff check v2 => All checks passed.
- 2026-06-21T20:21:09: Post-revenue-aggregation verification: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 70 passed, 1 Starlette/httpx deprecation warning; ruff format --check v2 => 665 files already formatted; ruff check v2 => All checks passed.
- 2026-06-21T20:24:17: Batched de-dupe scaling follow-up verification: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 70 passed, 1 existing Starlette/httpx deprecation warning; ruff format --check v2 => 665 files already formatted; ruff check v2 => All checks passed.
- 2026-06-21T20:24:50: Post-batched-dedupe verification: /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q => 70 passed, 1 Starlette/httpx deprecation warning; ruff format --check v2 => 665 files already formatted; ruff check v2 => All checks passed.
## Reusable Lessons

- None recorded yet.
