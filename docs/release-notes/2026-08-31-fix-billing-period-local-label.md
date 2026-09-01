# billing-period-local-label

PR: #604

## What changed
`QuoteEnrollment` derived the billing period label from the raw UTC
instant while `BillingPeriod.from_label` builds the period bounds in the
session's timezone, so for US tenants the label disagreed with its own
bounds for the several evening hours before local month-end (`#541`). An
8:15pm Chicago checkout on Aug 31 was labelled `2026-09`: the quote
priced a phantom September (which has no occurrences yet), the parent's
remaining August classes were never quoted or billed, and the zero-amount
branch stamped `zero_quote_period = "2026-09"` from a *second*, fresh
`datetime.now(UTC)` — skipping the whole of September's tuition once
admin approval copied it into `skip_periods`.

The label is now taken from the instant in the session's own timezone
(naive datetimes read as UTC, following the `#510` fix in commit
`118f4622`), and the $0 path reuses the quote's own
`billing_period_label` instead of re-deriving one.

Two further sites bucketed the same month on a different clock and are
fixed here too:

- A caller-supplied `start_date` was pinned to a **hardcoded**
  `America/Chicago` midnight in both composition layers. Harmless while
  the label came from UTC, but once the label became session-local it
  moved the quote a month *backwards* for any academy west of Chicago —
  `2026-09-01 00:00 CDT` is `2026-08-31 22:00 PDT` — so a Los Angeles
  academy asking for a September 1st start was quoted August, in which
  every class precedes the billing start, collapsing the quote to
  `$0.00`. The calendar date now travels down as a `date` and
  `QuoteEnrollment` resolves it against the session's own clock.
- The monthly generator's first-month gate
  (`_resolve_charge_for_enrollment`) compared a raw UTC
  `billing_start.strftime("%Y-%m")` against a local period label, so an
  enrollment created at 8:15pm Chicago on May 31 was misread as a
  first-month enrollment for June and **re-prorated**, undercharging a
  parent who attended the whole month.

## Deploy notes
No migration and no schema change. Only quotes minted during the local
evening of a month's last day change shape, plus quotes that pass an
explicit `start_date` for an academy outside `America/Chicago`; every
other instant is byte-identical to before.

Audit before the next generation run: applications already carrying a
`zero_quote_period` are untouched by this change, but any stamped
between local 7pm and midnight on a month's last day hold the *next*
month and will wrongly skip that month's tuition. Query
`onboarding_applications` for non-null `zero_quote_period`, cross-check
each against the local date of the application's checkout, and correct
`skip_periods` on any enrollment already stamped from one. This is
pre-existing bad data that the fix neither creates nor repairs.

## Risk / rollback
A month-end evening enrollment now quotes the current local month rather
than the next one, so its first invoice is a proration of the remaining
local month instead of a full next month — intended, but it moves money
between periods for exactly those enrollments, and a same-day-start
checkout in that window will often quote $0 and route into the
pending-approval branch instead of paying at checkout. The generator
change means a boundary enrollment is now billed full tuition in its
second month instead of a second proration, which *raises* collections
for those accounts.

Revert the merge to restore UTC labelling; nothing persisted needs
cleanup, though any `zero_quote_period` stamped while this was deployed
would revert to the old (wrong) semantics on the next quote.
