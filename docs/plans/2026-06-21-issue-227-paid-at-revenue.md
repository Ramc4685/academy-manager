# Issue 227 Paid At Revenue Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Make admin collected-cash reporting bucket successful revenue by payment-effective date instead of row creation date.

**Architecture:** Keep the change inside the existing v2 admin composition and billing finance read model. Use a shared effective-date helper for ledger and legacy payment rows so dashboard cash, P&L revenue, `/admin/finance/revenue`, and revenue CSV export agree.

**Tech Stack:** FastAPI v2 backend, Motor/Mongo-style queries, pytest, mongomock_motor.

---

## Current Behavior Found

- `backend/v2/composition/admin.py` filters dashboard `ledger_payments` by `created_at` for the selected UTC month.
- The same dashboard reads legacy `payments` by exact `period`, so legacy and ledger rows use different timing semantics.
- `profit_and_loss.revenue_cents` reuses `cash_collected_cents`, inheriting the dashboard basis.
- `list_payments_recent()` returns ledger rows with `created_at` but no `paid_at`; revenue CSV groups by `row["created_at"]`.
- `backend/v2/contexts/billing/application/use_cases/finance.py::AcademyRevenueQuery` groups legacy `Payment` rows by `p.created_at`.
- Existing dashboard and export tests cover tenant filtering and de-dupe, but do not create rows with different `paid_at` and `created_at`.

## Files Likely Affected

- Modify: `backend/v2/composition/admin.py`
- Modify: `backend/v2/contexts/billing/application/use_cases/finance.py`
- Modify: `backend/v2/tests/application/test_admin_reports_dashboard.py`
- Modify: `backend/v2/tests/unit/test_admin_composition_tenancy.py`
- Modify: `backend/v2/tests/interface/test_admin_billing.py`
- Possibly modify: `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py`
- Possibly modify: `backend/v2/tests/application/test_webhook_handler.py`

## Proposed Change

1. Add helper functions near existing report date helpers in `backend/v2/composition/admin.py`:
   - `_coerce_report_datetime(value) -> datetime | None`
   - `_payment_effective_at(row) -> datetime | None` preferring `paid_at`, then `payment_date`, then `created_at`, then period fallback as first day of the month.
   - `_payment_effective_month(row) -> str`
   - `_payment_effective_window_query(start, end) -> dict` using `$or`:
     - `paid_at` in month;
     - `paid_at` missing/null/empty and `payment_date` in month;
     - both missing and `created_at` in month.
2. Update dashboard `ledger_payments` query to use effective-date window logic with `paid_at` first and `created_at` fallback only when `paid_at` is missing.
3. Update dashboard legacy `payments` fallback to read candidate rows by effective-date window plus `period` compatibility fallback, then include only rows whose computed effective month equals the requested period.
4. Include `paid_at` in `list_payments_recent()` ledger rows and sort display rows by `created_at` as today.
5. Update revenue CSV export to bucket rows by `_payment_effective_month(row)` instead of `created_at`.
6. Replace the admin composition wiring for `/admin/finance/revenue` with a Mongo-backed effective-date revenue query that reads ledger rows first and de-dupes matching legacy rows by provider/invoice/payment keys.
7. Keep legacy `AcademyRevenueQuery` behavior compatible but change it to use `paid_at` when present on legacy `Payment`-like rows if tests expose that path.
8. Audit Stripe webhook payment writers. If provider timestamps are easily available in existing event payloads, map `paid_at` from them; otherwise document and test the existing fallback-to-processing-clock behavior in the ledger.

## Risks

- Mongo query portability: mongomock may not exactly match production behavior for missing/null date fields, so tests should verify the Python-level filtering too.
- Legacy rows without any date still need deterministic period fallback, but that is compatibility behavior rather than true cash timing.
- Refund netting remains against the original payment row/month; issue #227 asks for explicit definition, not a full refund-ledger redesign.
- `/admin/finance/revenue` currently used a legacy repository abstraction; introducing a Mongo reader in composition must preserve tenant scoping.
- The branch is based on issue #224, so final verification should include the focused billing/webhook checks touched by that base when practical.

## Verification Steps

1. RED tests:
   - Dashboard late ledger row: `paid_at=2026-05-31`, `created_at=2026-06-01` counts in May, not June.
   - Dashboard missing `paid_at` row falls back to `created_at`.
   - Legacy row uses `paid_at`/`payment_date`/`created_at` before `period`.
   - CSV revenue export buckets by `paid_at` and still de-dupes legacy projection.
   - `/api/v2/admin/finance/revenue` returns ledger revenue by `paid_at`.
2. GREEN focused tests:
   - `cd backend && source .venv/bin/activate && pytest v2/tests/application/test_admin_reports_dashboard.py v2/tests/unit/test_admin_composition_tenancy.py v2/tests/interface/test_admin_billing.py -q`
3. Style:
   - `cd backend && source .venv/bin/activate && ruff format --check v2 && ruff check v2`
4. If webhook timestamp code changes:
   - `cd backend && source .venv/bin/activate && pytest v2/tests/application/test_webhook_handler.py v2/tests/unit/test_charge_autopay_use_case.py -q`
5. Ledger:
   - Log test commands and any skipped checks in `docs/test-results/active/2026-06-21-issue-227-paid-at-revenue.md`.
