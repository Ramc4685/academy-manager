# billing-period-local-label

PR: #TBD

## What changed
`QuoteEnrollment` derived the billing period label from the raw UTC
instant while `BillingPeriod.from_label` builds the period bounds in the
session's timezone, so for US tenants the label disagreed with its own
bounds for the several evening hours before local month-end (`#541`). An
8:15pm Chicago checkout on Aug 31 was labelled `2026-09`: the quote
priced a phantom September (which has no occurrences yet), the parent's
remaining August classes were never quoted or billed, and the zero-amount
branch stamped `zero_quote_period = "2026-09"` from a *second*, fresh
`datetime.now(UTC)` — skipping the whole of September's tuition. The
label is now taken from the instant in the session's own timezone
(naive datetimes read as UTC, following the `#510` fix in commit
`118f4622`), and the $0 path reuses the quote's own
`billing_period_label` instead of re-deriving one.

## Deploy notes
No migration and no data changes. Only quotes minted during the local
evening of a month's last day change shape; every other instant is
byte-identical to before. Applications already carrying a
`zero_quote_period` are untouched — if any were stamped at a month-end
evening they hold the *next* month and will wrongly skip that month's
tuition, so audit `onboarding_applications` for `zero_quote_period`
values stamped between local 7pm and midnight on a month's last day
before the next generation run.

## Risk / rollback
A month-end evening enrollment now quotes the current local month rather
than the next one, so its first invoice is a proration of the remaining
local month instead of a full next month — intended, but it moves money
between periods for exactly those enrollments. Revert the merge to
restore UTC labelling; nothing persisted needs cleanup.
