# checkout-entry-cas

PR: #516

## What changed
`#499` added a compare-and-set to the checkout re-stamp, but that CAS only
fires once an application is already `CHECKOUT_PENDING` — and the first race
happens on the way in. The `DRAFT -> CHECKOUT_PENDING` write was a blind
`save` with no CAS and no retirement, and nothing upstream is idempotent (the
route takes no key, and `StartCheckout` mints a fresh ULID per call). Two
concurrent `POST /parent/checkout/start` calls against one DRAFT application
therefore both wrote, leaving two live payable Stripe sessions and only the
last-written `payment_id` — the sole handle `PaymentSucceeded` has to resolve
the application again. The entry transition now takes the same CAS:
`restamp_checkout` gains an optional `new_status` so the status move happens
in the same atomic write, and the loser retires the session it just minted
and raises `ApplicationNotEditable`, exactly as the re-stamp loser already did.

## Deploy notes
None beyond the normal deploy. No migration. No new Stripe call — the loser
path reuses the `expire_checkout_session` retirement `#499` already shipped.

## Risk / rollback
The parent-facing behaviour change is that the losing tab of a genuine double
start now gets a 409 (`Onboarding.ApplicationNotEditable`) instead of silently
taking ownership. That is the point — one payable session per application —
but it is a new user-visible failure on the checkout path, and
`frontend/lib/api/payment-error.ts` has no copy entry for that code yet, so
the loser tab shows the caller's generic fallback string. Applications that
already hold two live sessions from before this ships are not reconciled here.
Roll back by reverting the merge commit; the CAS persists no state, and
`new_status` is an optional argument that older callers simply do not pass.
