# Admin Payment Visibility & Financial Analytics — Design

**Date:** 2026-07-08 · **Approved by:** owner (RamC) · **Basis:** cash-basis revenue, per-academy scope

## Problem

An academy admin/owner cannot answer: who paid last, what payments came in recently, and what
income is coming next. The data exists in the AR ledger (`invoices`, `ledger_payments`,
`payment_allocations`) but is not surfaced. Additionally two revenue sources disagree:
`/finance/revenue` reads the legacy `payments` collection while the reports dashboard reads
`ledger_payments`.

## Industry reference (research summary)

Jackrabbit Class Executive Dashboard is the reference pattern for this market. The standard
report/widget set across Jackrabbit, iClassPro, Mindbody, Class Manager:

1. Payments received by date/method (deposit slip)
2. Revenue by program/category
3. AR aging (0-30/31-60/61-90/91+) with contact-the-family actions
4. Failed/declined autopay report + dashboard alert (highest ROI: 10-16% of recurring charges fail)
5. Billed vs collected
6. Refunds report
7. Projected recurring revenue
8. QuickBooks/Xero export — the industry does NOT build in-app expense entry/P&L beyond this

Open-source verdict: nothing embeddable (Kill Bill too heavy; Lago/Metabase/Crater AGPL;
Invoice Ninja Elastic License). Build aggregations over our own Mongo ledger; render with
shadcn/ui charts (Recharts, MIT).

## Phases

### Phase 1 — payments visibility (this branch: `feat/admin-payment-visibility`)

1. **Payments list upgrades** (`GET /admin/payments`, `frontend/app/(admin)/admin/payments/page.tsx`):
   - Filter by date range (on `paid_at` where present, else `created_at`), status, method.
   - Search by parent/student name.
   - Sort by payment date (most recent money first), pagination beyond the current 200 cap.
2. **Recent payments feed**: last-N succeeded payments (payer, student, amount, method, paid_at)
   surfaced as an endpoint + card on the owner dashboard (`/admin/reports`).
3. **Last payment per family**: expose most recent `paid_at` per parent so "who paid last" is
   answerable at a glance.
4. **Unify revenue source**: `/finance/revenue` (AcademyRevenueQuery) reads `ledger_payments`
   (cash-basis, net of refunds) so all revenue figures agree with the reports dashboard.

### Phase 2 — owner financial dashboard (separate session; task chip created)

Stat tiles (billed/collected/outstanding + collection rate), failed-autopay alert card with
retry/notify actions, AR aging widget with drill-down, projected next-month income
(enrollments × fee, autopay vs manual split), revenue trend vs prior year.

### Phase 3 — reports & exports (separate session; task chip created)

Refunds & credits report, revenue by program/session, deposit-slip report, QuickBooks-format
CSV export; extend `_EXPORT_REPORTS` allowlist in `reports_routes.py`.

## Recorded TODO (out of scope, do not lose)

- **Franchise cross-academy rollup**: all analytics are tenant-scoped per academy. A
  multi-location owner needs a rollup view (aggregate revenue/AR across academies). Revisit
  after Phase 3.

## Key code references

- Routes: `backend/v2/interfaces/admin/billing_routes.py` (list_payments), `reports_routes.py`
- Composition: `backend/v2/composition/admin.py` (`list_payments_recent` ~L4289,
  `get_reports_dashboard` ~L1420)
- Revenue query: `backend/v2/contexts/billing/application/use_cases/finance.py` (~L503)
- DTOs: `backend/v2/interfaces/admin/views.py` (`AdminPaymentView`, `AdminPaymentList`)
- Ledger domain: `backend/v2/contexts/billing/domain/ledger.py`
- Frontend: `frontend/app/(admin)/admin/payments/page.tsx`, `reports/page.tsx`
