# overnight-followups-2

PR: #TBD

## What changed
The single-invoice autopay idempotency key is now a hash of the invoice and its retry rung only, like the family key from #1193: a retry whose amount changed (for example the ACH discount dropping because the payment-method lookup failed) reuses the key, Stripe refuses it, and the rung parks instead of debiting the parent twice. A lost autopay charge that the daily recheck finds refunded, disputed or otherwise unsafe to settle now parks once as `existing_charge_needs_review` (shown to admins as needing attention) instead of re-parking every day. Manual-payment retries now claim through the shared idempotency store: a keyed retry after a failed recording runs at once instead of waiting a minute, a retry with the same key and a different payload is still rejected (the key stays bound to its first payload even after a failure), and a keyless submission is never recorded twice. On the admin user page, the roles panel no longer resets an edited selection when the profile form saves, so "Saved." can no longer be followed by the old role coming back; class and replacement-coach pickers offer only active coaches (a disabled coach already on a class stays shown). Percent-coach payroll now finds the tuition invoiced for a term class through its template, so a term class with paid monthly invoices no longer reports its occurrences as missing invoices and blocks payroll.

## Deploy notes
No migration. Single-invoice autopay keys change format once at deploy (the old ones carried the amount and fee), so a charge whose first answer was lost just before the deploy is not covered by Stripe's replay; deploy outside the dunning run. Manual payments in flight under the old claim document finish normally; the old claim documents are no longer read.

## Risk / rollback
Rungs parked as `existing_charge_needs_review` are not retried automatically; an admin must check the PaymentIntent in Stripe and settle or retry the invoice by hand. Payroll previews for term classes may now show a higher tuition base than before (the invoiced tuition was previously missed). Roll back by reverting the PR.
