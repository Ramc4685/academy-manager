# Scheduled price changes reach autopay start and forward-looking reports

PR: #TBD

## What changed

Follow-up to the scheduled plan price change (#1017). Every charge path
already read a class fee for a billing month through the month-aware read;
four forward-looking reads still used the stored fee directly.

- **Parent "start autopay"** now reads the fee of the month its first charge
  collects (the month after the current one, on the class's clock) through
  the same month-aware read as checkout. The silent $25 fallback for an
  unpriced class is gone: an unpriced class reads $0, exactly as checkout
  reads it (a $0 quote skips payment), so autopay refuses it with the same
  409 a non-active enrollment gets ("this class has no monthly fee"). Before,
  such a class went to Stripe setup as if it cost $25.
- **Projected income** (Reports, next month) uses the fee that month will be
  charged when the month is after the academy's current billing month.
- **Session economics** (Reports, per month) does the same for a future month.
- **Percent-of-revenue coach payroll** (the expected-revenue basis per
  occurrence) uses the month-aware fee for occurrences in a future month.

The current month and past months keep reading the stored fee, so payroll
for closed months and every report for past months are unchanged. With no
plan price change on record (BLNO today) every number is exactly as before.

Projections not changed, and why:
- Payouts derived from completed occurrences (`MongoPayoutRepository`) only
  cover occurrences that already ended: never a future month.

## Deploy notes

No migration, no config. One extra indexed `plan_price_changes` lookup per
report call (only when the month is in the future), and one academy
timezone read per call.

## Risk / rollback

Low. Revert the PR to restore the stored-fee reads. The only behaviour change
for BLNO is that starting autopay on a class with no fee at all is refused
instead of being set up at $25. Before deploy, count BLNO classes with none of
`amount_cents`, `monthly_price_cents`, `monthly_price` set (not checked here:
no prod access from this lane); any such class with an active enrollment
would now get the 409 instead of a $25 autopay setup.
