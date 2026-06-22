# issue 227 paid-at revenue

## Current State

Status: active

## Problem

Resolve PR review comments for paid_at revenue bucketing and ledger/legacy duplicate cash reporting.

## Changed Files

- None recorded yet.

## Log

- 2026-06-22T07:24:25 main/NA: Task ledger created.
- 2026-06-22T07:24:26 main/working: Resolved PR review comments: revenue successful statuses include paid, net revenue prefers received amounts, subscription IDs no longer dedupe payment projections, and dashboard suppresses legacy cash duplicates by ledger/provider/allocation keys.
## Verification

- No verification recorded yet.
- 2026-06-22T07:24:26: python3 -m py_compile backend/v2/composition/admin.py backend/v2/tests/application/test_admin_reports_dashboard.py backend/v2/tests/unit/test_admin_composition_tenancy.py -> passed
- 2026-06-22T07:24:26: cd backend && /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q -> 70 passed, 1 StarletteDeprecationWarning
- 2026-06-22T07:24:26: cd backend && /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff format --check v2 && /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff check v2 -> passed
## Reusable Lessons

- None recorded yet.
