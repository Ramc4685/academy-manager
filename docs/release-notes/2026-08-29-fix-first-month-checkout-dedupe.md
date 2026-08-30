# first-month-checkout-dedupe

PR: #562

## What changed
The first-month proration a parent pays at registration checkout was invisible
to the monthly invoice generator's dedupe. The checkout quote and its CONSUMED
`FIRST_MONTH_PRORATION` snapshot are persisted with `enrollment_id=None` (the
enrollment does not exist until admin approval), and the `StartCheckout`
Payment doc carries neither an enrollment_id nor a period — but both generator
dedupe layers key on enrollment_id (`{enrollment_id, period}` existing-payment
check and the CONSUMED-snapshot check in `mongo_monthly_billing.py`). A
generation run later in the same month — the scheduled `billing_day` run or an
admin manual re-run of POST generate — therefore treated the enrollment as
first-month, computed a fresh proration, and invoiced the same period again:
the parent paid twice. The zero-amount checkout path already protected itself
via `zero_quote_period -> add_skip_period`; the paid path stamped nothing.

Admin approval — the first moment the enrollment exists — now resolves the
paid period from the checkout payment's consumed calculation snapshot
(`payment.calculation_snapshot_id -> snapshot.billing_period_label`) through a
new `PaidPeriodResolver` port and stamps it onto the enrollment with
`add_skip_period`, mirroring the zero-quote path. The composition-root
resolver only returns a period for payments in a paid status
(`succeeded`/`paid`/`partially_refunded`) whose snapshot is a
`FIRST_MONTH_PRORATION` calculation. The generator already honors
`enrollment.skip_periods`, so the paid period is excluded from every
subsequent generation run for that month.

## Deploy notes
No migration and no new configuration. The stamp happens only on approvals
that occur after this deploys; enrollments approved before the deploy whose
first month was paid at checkout are still unprotected for the current period
— if a generation run has not yet happened this month, spot-check new
enrollees for an already-paid first month before the academy's `billing_day`
run (or stamp `skip_periods` on those enrollments by hand).

## Risk / rollback
Resolution deliberately fails closed: if the payment/snapshot lookup errors,
approval fails and is safely retryable — failing open would silently
reintroduce the double charge. The stamp itself is `$addToSet`, so replayed or
recovered approvals cannot duplicate it. Worst mis-stamp case would be
skipping a period the parent had not actually paid, which the resolver guards
against by requiring a paid-status payment tied to a first-month proration
snapshot. Roll back by reverting the merge commit; already-stamped
`skip_periods` entries are correct (they reflect a real paid period) and can
be left in place.
