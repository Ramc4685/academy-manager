# checkout-restamp-orphan

PR: #TBD

## What changed
Two residual races left open by #499 / #590, both in the superseded-checkout
path.

**1. A re-stamp could orphan a paid application.** An application sitting in
`CHECKOUT_PENDING` with `cs_first` / `pay-first` gets its `payment_id`
overwritten when a second tab wins the re-stamp CAS. If the parent completed
`cs_first` in the seconds before that — charge accepted at Stripe, webhook not
yet delivered — the late `checkout.session.completed` had nothing to resolve:
`get_by_payment_id` is the only handle it has, and the application no longer
carried that id. `execute_for_payment` then returned `None` with no log at all.

`Application` now carries `superseded_payment_ids`, and
`MongoApplicationRepository.restamp_checkout` `$addToSet`s the id it is
overwriting **in the same atomic update** as the overwrite — a follow-up write
could be lost to a crash in exactly the window that matters. `get_by_payment_id`
matches the archive as well as the live pointer, so the late webhook still finds
its application and still reaches `PENDING_APPROVAL`. Payment ids are unique per
attempt, so the `$or` can never resolve to two applications.

`execute_for_payment` no longer returns `None` on a miss; it raises
`Onboarding.ApplicationForPaymentNotFound`. The old `None` conflated "this
payment never had an onboarding context" (routine: invoices, subscription
renewals, admin-recorded payments) with "we lost the application for a payment
that did", and the cross-context handlers now name each case: the succeeded path
logs a WARNING under the stable marker `onboarding_application_unresolved_for_payment`,
the capacity-failure path logs ERROR, and the expiry path — where no money moved
— stays at INFO.

**2. Retirement swallowed transient Stripe failures.**
`RealStripeGateway.expire_checkout_session` turned *every* `StripeError` into a
bare `ValueError`, so `_expire_session` could not tell "already complete or
expired" (benign — the parent paid on the old tab) from "we never reached
Stripe" (the session is still open and payable). Both were logged at INFO and
forgotten.

The gateway now raises `StripeCheckoutSessionNotExpirable` for the terminal
refusal and `StripeTransientFailure` for connection errors, timeouts, rate
limits and 5xx; classification fails safe, so an unrecognised error counts as
transient. The terminal case keeps its INFO swallow. A transient failure is
logged at WARNING and the session id is upserted into a new
`unretired_checkout_sessions` collection with the error, the attempt count and
the associated payment id — a reconciliation handle where previously there was
none. A later successful retirement of the same id clears the row, so the
collection stays a live worklist rather than an append-only log. The failure is
still not re-raised: it must not unpick state the caller has already committed.

## Deploy notes
Migration `0157_checkout_orphan_reconciliation_indexes` adds indexes on
`onboarding_applications.payment_id` and
`onboarding_applications.superseded_payment_ids` (neither field was indexed
before — `get_by_payment_id` collection-scanned on every payment webhook) and
creates the `unretired_checkout_sessions` collection's unique and oldest-first
indexes. It runs at boot like every other migration; nothing to run by hand.

`unretired_checkout_sessions` is written but **nothing sweeps it yet**. It is a
worklist for a human or a future job: rows there are Stripe Checkout Sessions
believed to still be payable. Watch it after deploy — a steady stream means
Stripe connectivity problems, not a code regression.

Sessions orphaned by either bug BEFORE this deploy are not swept by this change.
Applications whose parent paid a since-superseded session are still stuck; they
have no `superseded_payment_ids` entry to find them by, so a backfill would have
to match pending/succeeded `ledger_payments` rows against
`onboarding_applications.stripe_checkout_session_id`.

## Risk / rollback
Low-to-moderate. `superseded_payment_ids` is additive with a `[]` default, so
documents written before this deploy read back unchanged and the `$or` simply
never matches on them.

The one behavioural change with reach beyond checkout is
`execute_for_payment` raising instead of returning `None`: every call site is in
`composition/event_handlers.py` and each now catches
`ApplicationForPaymentNotFound` explicitly, including the two inside the
capacity-failure refund block where an escaping exception would have been
misreported as a failed refund. Any future caller that forgets to catch it will
see a 404-mapped domain error rather than a silent no-op — which is the intent.

Rollback is a straight revert. The new collection and indexes can be left in
place; nothing reads them.
