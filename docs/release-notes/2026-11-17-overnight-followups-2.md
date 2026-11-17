# overnight-followups-2

PR: #1200

## What changed
The single-invoice autopay idempotency key is now a hash of the invoice and its retry rung only, like the family key from #1193: a retry whose amount changed (for example the ACH discount dropping because the payment-method lookup failed) reuses the key, Stripe refuses it, and the rung parks instead of debiting the parent twice. When the recheck finds a charge on the invoice it must not settle as this one (refunded, disputed, another amount, another set of invoices, or one that left a balance), the rung parks as `existing_charge_needs_review`: it is never charged again, the family shows under Failed autopay and on billing-health (even on a first attempt), and once a day the ladder rechecks without calling Stripe, so recording a manual payment or voiding the invoice stands it down. Manual-payment retries now claim through the shared idempotency store: a keyed retry after a failed recording runs at once instead of waiting a minute, the same key with a different payload is rejected with 422 even while the first submission is still running or after it failed, and a keyless submission is never recorded twice. On the admin user page, the roles panel no longer resets an edited selection when the profile form saves, so "Saved." can no longer be followed by the old role coming back; class and replacement-coach pickers offer only active coaches (a disabled coach already on a class stays shown). Percent-coach payroll now finds the tuition invoiced for a term class through its template, so a term class with paid monthly invoices no longer reports its occurrences as missing invoices and blocks payroll.

## Deploy notes
No migration. Single-invoice autopay keys change format once at deploy (the old ones carried the amount and fee), so a charge whose answer was lost before the deploy is not covered by Stripe's replay. Before deploying, run this on production and deploy only if it returns nothing:

```
db.dunning_states.find({
  next_attempt_at: null,
  status: { $in: ["active", "processing"] },
  suppression_reason: { $in: ["charge_technical_failure", "attempt_indeterminate", "stripe_unavailable", "technical_failure_capped"] }
}, { academy_id: 1, invoice_id: 1, suppression_reason: 1, suppressed_at: 1 })
```

If it returns rows, check each invoice's PaymentIntents in Stripe (settle any that succeeded) or wait 24 hours after the newest `suppressed_at`, then re-run it. Manual-payment claims left by the old code have no `claimed_at`; a keyed retry takes them over at once and is still held to the payload the old claim recorded.

## Risk / rollback
Rungs parked as `existing_charge_needs_review` are never charged automatically; an admin checks the PaymentIntent in Stripe and settles, voids or retries the invoice by hand. They are not charged late fees or sent reminders while parked, because the hold-up is on our side. Payroll previews change for term classes: a term class now gets its share of the tuition invoiced to its template, which raises a class that showed none and can lower the template's share where the two split the month. Roll back by reverting the PR.
