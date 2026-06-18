# admin session economics

## Current State

Status: archived

## Problem

Add an admin-visible /admin/session-economics page showing monthly session revenue, paid/unpaid, coach cost, expenses, and expected profit.

## Changed Files

- `backend/v2/composition/admin.py`
- `backend/v2/interfaces/admin/deps.py`
- `backend/v2/interfaces/admin/reports_routes.py`
- `backend/v2/interfaces/admin/views.py`
- `backend/v2/tests/application/test_admin_reports_dashboard.py`
- `backend/v2/tests/interface/test_admin_reports_dashboard.py`
- `frontend/app/(admin)/admin/session-economics/page.tsx`
- `frontend/components/admin/screen-meta.ts`
- `frontend/lib/api/admin.ts`
- `docs/plans/2026-06-18-admin-session-economics.md`

## Log

- 2026-06-18T12:17:19 main/NA: Task ledger created.
- 2026-06-18T12:28:06 main/working: Added admin-visible /admin/session-economics feature: v2 reports endpoint, session-level economics calculation, frontend API types, nav metadata, and dedicated page.
## Verification

- No verification recorded yet.
- 2026-06-18T12:28:06: Backend focused report tests: cd backend && source .venv/bin/activate && pytest v2/tests/interface/test_admin_reports_dashboard.py v2/tests/application/test_admin_reports_dashboard.py -q -> 9 passed, 1 Starlette/httpx deprecation warning.
- 2026-06-18T12:28:15: Frontend checks: cd frontend && pnpm typecheck -> passed; cd frontend && pnpm lint -> passed with 5 existing warnings in unrelated files.
- 2026-06-18T12:28:15: Local smoke: scripts/local_test_stack.sh smoke -> MongoDB, Firebase Auth/UI, backend API, frontend running; backend health ok; frontend BFF proxy ok. Manual authenticated browser check not completed because seeded local auth data would require destructive seed/reset approval.
- 2026-06-18T12:28:15: Backend lint/format on touched files: ruff format --check and ruff check -> all checks passed.
- 2026-06-18T12:28:06: Broader backend payout/report set: pytest v2/tests/contract/test_payable_occurrence_query.py v2/tests/contract/test_occurrence_completion_derivation.py v2/tests/contract/test_coach_rate_repo.py v2/tests/application/test_coach_payout.py v2/tests/application/test_manage_payout_period.py v2/tests/interface/test_admin_payout_periods.py v2/tests/interface/test_admin_coach_pay_rates.py v2/tests/interface/test_admin_reports_dashboard.py v2/tests/application/test_admin_reports_dashboard.py -q -> 61 passed, 1 Starlette/httpx deprecation warning.
## Reusable Lessons

- None recorded yet.
