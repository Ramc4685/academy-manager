# billing-health-trim

PR: #686

## What changed
Billing Health is now Stripe plumbing only: one health verdict computed on the backend (it can no longer report "System healthy" for an academy that cannot take a payment), quarantined webhooks with replay, reconciliation runs plus the lookup moved here from the Payments page, and a "link a Stripe charge to an invoice" form replacing the misleading legacy-match list. The failed-attempts and dunning sections are gone — the Payments Failed autopay bucket and the Family timeline own them. The page is now **owner-only**.

## Deploy notes
No migration, no data change, no env. Note the access change: admins who are not owners now get a 404 on `/admin/billing-health`, and the nav item is hidden for them. The routes `GET /admin/billing/failed-payment-attempts`, `GET /admin/billing/dunning` and `GET /admin/billing/invoices/{id}/attempts` are deliberately left alive with no caller until the Month close PR lands; deleting them is a follow-up.

## Risk / rollback
The charge-linking path was hardened in this PR: it now verifies the charge against Stripe (succeeded, unrefunded, currency and amount matched), binds it to the invoice's parent, and refuses a charge already recorded — previously a typo could book money nobody paid, and a webhook replay could double-book. `ledger_payments.stripe_payment_intent_id` still has no unique index behind it; see #679. Rollback by reverting the PR — no stored data changes shape.
