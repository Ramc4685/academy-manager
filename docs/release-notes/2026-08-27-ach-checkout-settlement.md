# ach-checkout-settlement

PR: #461

## What changed
Stripe Checkout payments made with ACH no longer mark an invoice paid at
`checkout.session.completed`. That event fires with `payment_status: "unpaid"`
for delayed-notification methods, so the invoice now stays open with a
`processing` payment attempt until `checkout.session.async_payment_succeeded`
confirms the funds landed; `checkout.session.async_payment_failed` records the
failure and leaves the invoice open and payable. Dunning keeps running until the
money is actually there.

## Deploy notes
No migration. **Manual step:** add `checkout.session.async_payment_succeeded` and
`checkout.session.async_payment_failed` to the enabled events on the existing
production Stripe webhook endpoint (Stripe Dashboard → Developers → Webhooks).
`scripts/prod/create_stripe_webhook_and_set_secrets.sh` only sets the event list
when it creates a new endpoint; the live endpoint already exists. Without this,
ACH checkouts park as `processing` and are only credited later by the scheduled
PaymentIntent reconciliation. The local/Docker staging list
(`scripts/dev/saas_staging.sh`) is updated automatically.

## Risk / rollback
If the gate is wrong, an ACH checkout stays open longer than it should — money
is under-credited rather than falsely credited, and the scheduled PaymentIntent
reconciliation still repairs it once the PaymentIntent reads `succeeded`. Card
checkouts are unaffected (`payment_status` is `paid` inline). Roll back by
reverting the PR; no data is written that a revert would strand, since the new
rows are `payment_attempts` history only.
