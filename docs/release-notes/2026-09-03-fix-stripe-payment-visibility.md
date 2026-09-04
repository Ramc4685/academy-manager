# fix-stripe-payment-visibility

PR: #645

## What changed
Reported from the prod admin dashboard on 2026-09-03: Stripe and manual
payments were not showing under "Recent payments", and an expired checkout
appeared twice.

**Root cause (BFF).** `list_payments_recent` in `backend/v2/composition/admin.py`
is invoice-centric. When a `ledger_payments` or legacy `payments` document
settled an invoice, the payment row was dropped in favour of the invoice row and
nothing was carried across. On prod, 193 of 200 rows came back as method
`invoice`, `paid_at: null`, `stripe_linked: false`, while the paid-only feed
showed 13 Stripe/Zelle settlements in the same window. The dashboard then
sorted that list by `created_at` (invoice creation), so real settlements sank
below registration checkouts and expired attempts.

- New `backend/v2/contexts/billing/application/admin_payment_settlement.py`:
  `apply_settlement` folds `paid_at`, the real `payment_method`
  (`stripe_checkout`, `zelle`, ...) and Stripe ids onto the matched invoice row.
  Only money-received statuses (`succeeded`, `paid`, `refunded`,
  `partially_refunded`) settle; pending/failed/expired attempts never touch an
  invoice row.
- One ledger payment can settle several invoices (balance checkouts write one
  allocation per invoice): allocations are batch-loaded and every allocated
  invoice row is settled, not just the first one found.
- The ledger window is read money-received first, then attempts, so a burst of
  pending/failed attempts cannot push the payment that actually settled an
  invoice out of the fold.
- `payment_method = "stripe"` is a real ledger method (webhook), not a
  placeholder; an older settlement never overwrites it.
- Standalone ledger rows with Stripe ids but no method are labelled
  `stripe_checkout` and `stripe_linked`.
- Legacy rows sharing a `payment_id` or checkout session with a ledger row are
  deduped (the duplicated expired checkout).
- Dashboard "Recent payments" (`frontend/app/(admin)/admin/page.tsx`) now reads
  `/admin/payments/feed` (money received, newest settlement first) and shows a
  Method column. Expired/failed attempts no longer appear there.
- Payments page: the method chip shows the real settlement method — an invoice
  with a Stripe invoice id that was paid by Zelle reads "ZELLE", not "STRIPE";
  invoice-row detection keys off `invoice_id`, not the method string.
- Payments page and Reports feed label every `stripe_*` method as "Stripe";
  "Paid on" now populates for Stripe-settled invoices.
- Tests: nine new composition/unit tests in
  `backend/v2/tests/unit/test_admin_payment_visibility.py`; dashboard e2e stubs
  the feed.

## Deploy notes
No migration, no config. Safe to deploy immediately. After deploy, open
`/admin` and confirm "Recent payments" lists the latest Stripe/Zelle
settlements with a Method chip, and `/admin/payments` shows a "Paid on" date on
Stripe-paid invoices.

## Risk / rollback
Low. Read-model shaping only; no writes change. Rollback is a revert of this PR.
