# autopay-recheck-and-followups

PR: TBD

## What changed
An autopay charge no longer bills full price when Stripe can't tell us the saved payment method's type while an ACH cash discount is switched on: the rung parks as `stripe_unavailable` and the next tick charges the discounted amount, on the first attempt and on retries, for single and family charges (it used to drop the discount, and on a retry delete the discount line). When Stripe refuses a reused idempotency key because the request changed, the rung now parks as `existing_charge_needs_review` for a person instead of retrying hourly as if Stripe were down. The test Stripe double now compares the whole request on a reused key, the way Stripe does, not just the amount.

## Deploy notes
No migration, no env change, and the charge keys are unchanged. Deploy outside the dunning run (avoid :04 to :20 UTC). Before deploying, list rungs parked as `stripe_unavailable` (`db.dunning_states.find({status: "active", suppression_reason: "stripe_unavailable"}, {academy_id: 1, invoice_id: 1, parked_since: 1})`); any that were parked by a refused key will move to `existing_charge_needs_review` on their next retry and show under Failed autopay, so check their PaymentIntents in Stripe. A billing-settings read failure during a charge now parks the rung as a technical failure instead of charging without the discount.

## Risk / rollback
While Stripe's payment-method read is failing, academies with the ACH discount on will see rungs park and retry hourly (capped after 24h) instead of charging; card payers there wait one tick too. A refused-key rung is never charged automatically until an admin settles, voids or retries it. Roll back by reverting the PR.
