# registration-decline-refund

PR: #567

## What changed
The audited `CHECKOUT_PENDING -> CAPACITY_FAILED_REFUNDING -> REFUNDED`
auto-refund flow was unreachable dead code (`#514`): its only trigger,
`ConfirmEnrollment`, is wired but never invoked, so a parent who paid at
checkout and whose session filled before admin review had their captured
payment silently retained when the application was declined.
`AdminRegistrationReview.reject()` now refunds the remaining captured
amount through Billing's idempotent `IssueRefund` use case before
recording the decline. A new `RegistrationDeclineRefunds` adapter checks
refundability first — missing payment, never captured
(`pending`/`failed`/`expired`/`waived`), zero-amount, or already fully
refunded payments are a no-op, so declining unpaid applications is
unchanged. A refund failure aborts the decline and releases the
application back to `PENDING_APPROVAL`, surfacing the error to the admin
instead of losing the parent's money. `registration_declined` is added
as a first-class refund reason on the `PaymentRefunded` event.

## Deploy notes
No migration, no config. Behavior change is admin-facing only: declining
a paid registration now issues a Stripe refund for the remaining
captured amount, and a failed refund makes the decline fail loudly
(retry once Stripe is healthy — the refund is idempotent, so retries
cannot double-refund).

## Risk / rollback
Low. The refund port is optional and only wired in the admin composition
root; every other reject/waitlist/approve path is untouched (780
application tests green, mypy baseline clean). Worst case is a decline
that used to "succeed" (while silently keeping the money) now erroring
until the refund goes through — that is the intended fix. Rollback:
revert the merge; declines then stop refunding again, so any reverts
should re-open `#514`.
