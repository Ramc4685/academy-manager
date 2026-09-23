# Billing tab shows refunded and net amounts (#929)

PR: #TBD

## What changed

- **Read model.** `MongoFamilyBillingReadModel` (`GET /admin/families/{parent_id}/billing`) now reads the invoice's `refunded_cents`. It also reads each payment's cumulative refund from `ledger_payments` and the legacy `payments` row. Both queries are academy-scoped. The pure builder (`contexts/billing/application/family_billing.py`) sends these fields:
  - **Invoice row:** `refunded_cents` and `net_paid_cents` (paid minus refunded, never below zero). A refund still does not reopen `balance_due_cents`.
  - **Refund issued timeline entry:** `amount_cents` is now set. It is that refund's own amount: the audit row's `after` minus `before`, not the running total. The summary reads "Refund issued · $25 · reason".
  - **Payment received timeline entry:** carries `refunded_cents`, and the summary adds "· $X refunded". `header.last_payment` carries `refunded_cents` and `net_cents`. A payment's refund is the largest of three records, never their sum: the two payment stores and the sum of that payment's audited refunds.
  - **Family totals:** `header.paid_cents`, `header.refunded_cents` and `header.net_paid_cents`, added up over the invoices on the page.
- **Refunds made in Stripe.** A refund made in the Stripe dashboard leaves no audit row. It now shows on the invoice row, the payment and the family totals, because the webhook already writes the invoice's `refunded_cents` and the ledger payment's refund.
- **Refund action.** The `refund` action is no longer offered on an invoice whose card money has all been refunded. The Refund dialog's ceiling is now the card money minus earlier refunds, not the full card amount again.
- **Response model and frontend.** `families_views.py` gains the new optional fields, so `extra="ignore"` no longer drops them. `frontend/lib/api/admin-families.ts` has the matching types. `InvoicesPanel` shows "$25.00 refunded · $35.00 net" on the row. `FamilyHeader` adds the refund to the Last payment tile and shows a family totals line (`family-refunds`) when the family has had a refund.
- **Staff tiers.** No new tier logic. The Billing tab already showed amounts to every admin-persona caller, and #553 is not built. Only the owner-only Refund action is still removed for non-owners.
- **Tests.** Real-mongod tests in `backend/v2/tests/contract/test_family_billing_money_path.py`. The strict xfail `test_refunded_amount_is_visible_on_the_billing_tab` is replaced by a passing test. New tests cover: two partial refunds (amount of each), a full refund (no further Refund action), a Stripe-dashboard refund with no audit row across two invoices (family totals), and the response model with non-owner stripping. Vitest cases for the new helpers are in `family-view.test.ts`.

## Deploy notes

- No migration. `refunded_cents` already exists on invoice and payment documents. A missing field reads as 0.
- Additive API fields only. Older clients ignore them.

## Risk / rollback

- Low. Read-only change to one admin read model plus display. No write path changed.
- Payment refunds are a best lower bound. The admin refund route can record the payment-side total on a different store than the one it reads when a legacy `payments` row and a `ledger_payments` row share a payment id. The view takes the largest record, so it does not undercount refunds issued in the app. The write-side drift is a separate follow-up.
- Rollback: revert the PR. There is no data to undo.
