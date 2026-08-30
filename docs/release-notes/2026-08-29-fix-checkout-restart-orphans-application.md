# checkout-restart-orphans-application

PR: #499

## What changed
`StartApplication` now resumes an existing CHECKOUT_PENDING application instead
of minting a new DRAFT, so returning from a cancelled Stripe checkout no longer
abandons an application that still holds a live payable session. The
`CHECKOUT_PENDING -> DRAFT` edge is declared in `_TRANSITIONS` and the resume is
a compare-and-set, so a parent who paid in another tab is never pulled back out
of PENDING_APPROVAL. A resumed application keeps its `payment_id` so a late
`PaymentSucceeded` can still find it, which is why `DRAFT -> PENDING_APPROVAL`
is now legal. Superseded checkout attempts are retired: a new
`StripeGateway.expire_checkout_session` expires the old session and its pending
Payment is parked as `expired`, on both the resume and re-stamp paths. The
re-stamp write is now a CAS instead of a read-then-blind-`$set`, and
`_assert_child_not_enrolled` runs on that branch too.

## Deploy notes
None beyond the normal deploy. No migration. The new Stripe call is
`checkout.Session.expire`, which the existing API key already covers.

## Risk / rollback
Behaviour change worth watching: because the wizard calls start on mount,
opening `/parent/onboarding` in a second tab while the parent is mid-payment on
Stripe now EXPIRES that live session. This is the intended trade — one payable
session per application, so the double-charge path closes — but a parent who
tabs back and forth will have to restart checkout. Retirement failures are
logged and swallowed so a Stripe hiccup cannot block a legitimate restart, and
a Payment that is not `pending` is never touched, so a succeeded charge can
never be parked. Roll back by reverting the merge commit; nothing persists
state that a revert would strand, though applications resumed while the change
was live will simply behave as ordinary DRAFTs afterwards.
