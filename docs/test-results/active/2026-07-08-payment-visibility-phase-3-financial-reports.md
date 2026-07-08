# Payment visibility phase 3 financial reports

## Current State

Status: active

## Problem

Admins lack the standard report set (refunds/credits, revenue by category, deposit slip, QuickBooks export); build cash-basis per-academy reports over the AR ledger with CSV export allowlist extension.

## Changed Files

- `backend/v2/composition/admin.py`
- `backend/v2/interfaces/admin/reports_routes.py`
- `backend/v2/interfaces/admin/views.py`
- `backend/v2/interfaces/admin/deps.py`
- `frontend/lib/api/admin.ts`
- `frontend/app/(admin)/admin/reports/page.tsx`
- `frontend/app/(admin)/admin/reports/refunds/page.tsx`
- `frontend/app/(admin)/admin/reports/revenue-by-category/page.tsx`
- `frontend/app/(admin)/admin/reports/deposit-slip/page.tsx`
- `frontend/components/admin/screen-meta.ts`

## Log

- 2026-07-08T09:18:30 main/NA: Task ledger created.

## Verification

- No verification recorded yet.
- 2026-07-08T09:19:16: backend: pytest v2/tests -q → 2164 passed; ruff check v2 + ruff format --check v2 clean; lint-imports 4 contracts kept. New tests: v2/tests/application/test_admin_financial_reports.py (6, mongomock incl. tenant isolation + QuickBooks JE balance) and v2/tests/interface/test_admin_financial_reports_routes.py (14). frontend: pnpm typecheck clean; pnpm lint 0 errors (5 pre-existing warnings in untouched files).
## Reusable Lessons

- None recorded yet.
