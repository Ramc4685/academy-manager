# Scheduled price changes reach autopay start and forward-looking reports

PR: #1021

## What changed

Follow-up to the scheduled plan price change (#1017). Every charge path
already read a class fee for a billing month through the month-aware read;
four forward-looking reads still used the stored fee directly.

- **Parent "start autopay"** now reads the fee of the month its first charge
  collects (the month after the current one, on the class's clock) through
  the same month-aware read as checkout. The silent $25 fallback for an
  unpriced class is gone: an unpriced class reads $0, exactly as checkout
  reads it (a $0 quote skips payment), so autopay refuses it with a 409
  carrying its own code, `Billing.AutopayClassUnpriced`. The parent payments
  page shows "This class doesn't have a monthly fee set yet, so autopay can't
  be started. Please contact the academy." instead of the generic failure.
  Before, such a class went to Stripe setup as if it cost $25.
- **Projected income** (Reports, next month) uses the fee that month will be
  charged when the month is after the academy's current billing month.
- **Session economics** (Reports, per month) does the same for a future month.
- **Percent-of-revenue coach payroll** (the expected-revenue basis per
  occurrence) uses the month-aware fee for occurrences in a future month.

A past month reads the fee it was billed at: once the daily job has flipped
a class at a change's month M, the stored fee is the new one, and these
reads undo the flip for months before M. So payroll and reports for closed
months do not move when a change takes effect (before, a recompute after
the flip read the new fee for every past month). The current month keeps
reading the stored fee. With no plan price change on record (BLNO today)
every number is exactly as before.

Known limits (unchanged by this PR):
- Between the start of month M and the daily flip job running (up to a
  day), the charge paths already bill the new fee while the current-month
  report reads the stored (still old) fee.
- The payroll basis buckets occurrences by UTC calendar month; an academy
  whose clock is behind UTC sees its last few evening hours of a month
  bucketed into the next month (and priced at that month's fee).
- Reports compare the requested month with the academy-clock current month;
  month bounds use the reporting timezone. The two only differ if a tenant's
  reporting timezone differs from its academy clock.

Projections not changed, and why:
- Payouts derived from completed occurrences (`MongoPayoutRepository`) only
  cover occurrences that already ended: never a future month.

## Deploy notes

No migration, no config. One extra indexed `plan_price_changes` lookup per
report call (any month but the current one), and one academy timezone read
per call.

## Risk / rollback

Low. Revert the PR to restore the stored-fee reads. The only behaviour change
for BLNO is that starting autopay on a class with no fee at all is refused
instead of being set up at $25. Before deploy, count BLNO classes with none of
`amount_cents`, `monthly_price_cents`, `monthly_price` set (not checked here:
no prod access from this lane); any such class with an active enrollment
would now get the 409 instead of a $25 autopay setup.
