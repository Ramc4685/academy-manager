# batch-4-billing-core-ledger

PR: #795

## What changed

- Fixes #659 — Parent-facing billing emails (invoice emails, autopay pre-charge notices, autopay receipts, dunning notices) now name the tuition month in words, the student, and the class in both subject and body — e.g. "September 2026 tuition for Arjun — Sat 09:00 Beginners" — instead of printing the raw period code (`2026-09`) or the internal invoice slug.
- Fixes #692 — `LedgerInvoice` now carries a `delivery_kind` (`invoice_email` | `autopay_notice`), stamped by `record_delivery` only on a successful send, so a failed retry can no longer erase what the parent actually received.
- Fixes #619 — Ledger payments gain a void state: a new owner-only `POST /admin/payments/{id}/void` reverses allocations through the existing `reverse_payment_allocation` machinery (reopening invoice balances and writing a `payment_allocation_reversals` audit row), zeroes unapplied funds, and appends a `payment_voided` billing-audit entry. Nothing is deleted. Stripe-linked payments with settled funds are refused with a pointer to the refund flow; EXPIRED/failed checkout rows are freely voidable. `GET /admin/payments` hides voided rows unless `include_voided=true`. Admin UI gains an owner-only Void action (reason required), a "Show voided" checkbox, and a VOID chip on voided rows.
- Fixes #608 — Admin financial reports now bucket months on the academy's IANA timezone instead of UTC (`month_bounds`, `month_label`, and both `$dateToString` revenue stages carry the academy's timezone; the owner rollup's `_month_key` converts BSON dates while legacy ISO strings keep their as-written `YYYY-MM`).
- Fixes #526 — The reports dashboard's cash reader no longer streams every succeeded `ledger_payments` doc the academy has ever recorded just to de-dup against legacy `payments` rows; the collision is now a batched `$or`/`$in` lookup by provider key, and the allocated-invoice pass is inverted the same way with a re-check that the ledger payment is successful. This is an exact-equivalence rewrite (no report numbers move).
- Fixes #693 — The deposit slip now builds its day/method buckets from the shared `cash_received_in_period` reader instead of its own `ledger_payments` scan, so it counts the same money month close counts (actual paid/received amount, not the amount charged) plus de-duplicated legacy cash. The QuickBooks journal's Undeposited Funds debit now derives from the slip's corrected total. Refunds remain un-netted from the slip by deliberate design (documented in both files); the journal books refunds separately.

## Deploy notes

Includes migrations:
- `backend/v2/migrations/0176_backfill_ledger_delivery_kind.py`
- `backend/v2/migrations/0177_ledger_payment_voided_state.py` (widens the `ledger_payments` status enum so voiding isn't rejected with `schemaRulesNotSatisfied`; adds an `(academy_id, status, created_at)` index)
- `backend/v2/migrations/0178_provider_key_dedup_indexes.py` (adds `invoice_id`/`invoice_number` indexes on both payment collections and `stripe_checkout_session_id` on `ledger_payments`)

Confirm `V2_RUN_MIGRATIONS_ON_BOOT` covers these or run them manually per AGENTS.md before/at deploy.

Historical deposit-slip and QuickBooks journal exports will change retroactively for any past month where a payment settled for less than it was charged, or where legacy cash existed (#693) — this is expected and intentional, not a regression.

## Risk / rollback

Risk is concentrated in the payments/reporting money paths: revenue de-dup rewrite (#526), month-bucketing timezone change (#608), and the deposit-slip/QuickBooks source-of-truth change (#693) all touch numbers finance staff read directly. Each is covered by tests pinning the new behavior against the old (exact-equivalence for #526, no report-number drift). The new void endpoint (#619) is owner-only, additive (nothing deleted), and refuses to void settled Stripe funds. If any of this regresses in prod, revert this PR's merge commit; the widened status enum from migration 0177 is backward compatible and does not need to be rolled back separately.
