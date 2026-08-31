# checkout-restamp-orphan

PR: #601

## What changed
Two residual races left open by #499 / #590, both in the superseded-checkout
path.

**1. A re-stamp could orphan a paid application.** An application sitting in
`CHECKOUT_PENDING` with `cs_first` / `pay-first` gets its `payment_id`
overwritten when a second tab wins the re-stamp CAS. If the parent completed
`cs_first` in the seconds before that — charge accepted at Stripe, webhook not
yet delivered — the late `checkout.session.completed` had nothing to resolve:
a payment id is the only handle it has, and the application no longer carried
that one. `execute_for_payment` then returned `None` with no log at all.

`Application` now carries `superseded_payment_ids`, and
`MongoApplicationRepository.restamp_checkout` `$addToSet`s the id it is
overwriting **in the same atomic update** as the overwrite — a follow-up write
could be lost to a crash in exactly the window that matters.

The archive is a **one-way door**: it may advance an application, never retire
one. `get_by_payment_id` still matches the live `payment_id` only; the archive
is a separate lookup, `get_by_superseded_payment_id`, and
`execute_for_payment` consults it for `PENDING_APPROVAL` and nothing else.
That asymmetry is the safety property. Retiring the superseded attempt is what
*makes* Stripe emit `checkout.session.expired` for it, and the webhook's own
`payment.status == "pending"` guard is armed by a write that is neither atomic
with the CAS nor exception-guarded — so a stale expiry for the replaced attempt
does reach the transition. Answering it from the archive would park the
application in `CHECKOUT_EXPIRED`, which has no outgoing transition and is not
a status checkout can be restarted from, while the parent pays the live
attempt: charged, unadvanced and unrecoverable. Strictly worse than the orphan
being repaired. Payment ids are unique per attempt, so neither lookup can
resolve to two applications.

`execute_for_payment` no longer returns `None` on a miss; it raises
`Onboarding.ApplicationForPaymentNotFound`. The old `None` conflated "this
payment never had an onboarding context" (routine: invoices, subscription
renewals, admin-recorded payments) with "we lost the application for a payment
that did", and the cross-context handlers now name each case: the succeeded path
logs a WARNING under the stable marker `onboarding_application_unresolved_for_payment`,
the capacity-failure path logs ERROR, and the expiry path — where no money moved
— stays at INFO. The succeeded path also catches `ApplicationNotEditable` under
the same marker at ERROR: an application found but stuck somewhere a paid
registration cannot advance from is the charged-but-unadvanced case the marker
exists to page on, and it used to escape the handler unclassified.

**2. Retirement swallowed transient Stripe failures.**
`RealStripeGateway.expire_checkout_session` turned *every* `StripeError` into a
bare `ValueError`, so `_expire_session` could not tell "already complete or
expired" (benign — the parent paid on the old tab) from "we never reached
Stripe" (the session is still open and payable). Both were logged at INFO and
forgotten.

The gateway now raises `StripeCheckoutSessionNotExpirable` for the terminal
refusal and `StripeTransientFailure` for everything else. The polarity is the
inverse of the obvious one and that is deliberate: the classifier asks "is this
the deterministic *session is no longer open* refusal?" — a 400
`InvalidRequestError` naming that state — and treats every other failure as
transient. Asking "is this transient?" and defaulting to terminal quietly files
a rotated or wrong-mode API key (401), a restricted key without checkout write
scope (403) and a platform/connected-account id mismatch (404
`resource_missing`) as "already paid" while the session is still wide open —
the exact swallow this issue exists to remove. Defaulting to transient costs at
most a spurious reconciliation row.

The terminal case keeps its INFO swallow. A transient failure is logged at
WARNING and the session id is upserted into a new `unretired_checkout_sessions`
collection with the error, the attempt count and the associated payment id — a
reconciliation handle where previously there was none. A later successful
retirement of the same id clears the row, so the collection stays a live
worklist rather than an append-only log. The failure is still not re-raised: it
must not unpick state the caller has already committed.

## Deploy notes
Migration `0157_checkout_orphan_reconciliation_indexes` adds indexes on
`onboarding_applications.payment_id` and
`onboarding_applications.superseded_payment_ids` (neither field was indexed
before — the payment lookup collection-scanned on every payment webhook) and
creates the `unretired_checkout_sessions` collection's unique and oldest-first
indexes. It runs at boot like every other migration; nothing to run by hand.

`unretired_checkout_sessions` is written but **nothing sweeps it yet**. It is a
worklist for a human or a future job: rows there are Stripe Checkout Sessions
believed to still be payable. Watch it after deploy — a steady stream means
Stripe connectivity or credential problems, not a code regression. Because
classification defaults to transient, an auth/permission misconfiguration shows
up here as a burst of rows rather than as silence.

New log marker to wire into alerting:
`onboarding_application_unresolved_for_payment` (WARNING on the
`PaymentSucceeded` path, ERROR on the capacity-failure path and on an illegal
transition for a succeeded registration payment). On the succeeded path it also
fires for every non-onboarding payment, so alert on a **rate change**, not on
any single occurrence.

Sessions and applications orphaned by either bug BEFORE this deploy are not
swept by this change. Applications whose parent paid a since-superseded session
are still stuck; they have no `superseded_payment_ids` entry to find them by, so
a backfill would have to match pending/succeeded `ledger_payments` rows against
`onboarding_applications.stripe_checkout_session_id`.

## Risk / rollback
Low-to-moderate. `superseded_payment_ids` is additive with a `[]` default, so
documents written before this deploy read back unchanged and the archive lookup
simply never matches on them. `get_by_payment_id` keeps exactly its pre-change
query, so no existing caller widens.

The one behavioural change with reach beyond checkout is `execute_for_payment`
raising instead of returning `None`: every call site is in
`composition/event_handlers.py` and each now catches
`ApplicationForPaymentNotFound` explicitly, including the two inside the
capacity-failure refund block where an escaping exception would have been
misreported as a failed refund. Any future caller that forgets to catch it will
see a 404-mapped domain error rather than a silent no-op — which is the intent.

The Stripe classifier's terminal branch matches on the refusal message, which is
a heuristic. It fails safe in the direction that matters: an unrecognised
message is treated as transient and lands on the worklist, so a future
stripe-python or wording change makes the worklist noisier, never quieter. It
cannot regress into swallowing a payable session.

Rollback is a straight revert. The new collection and indexes can be left in
place; nothing reads them.
