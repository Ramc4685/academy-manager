# class-credits-visibility

PR: #1210

## What changed
Owners can now see the credits families get when a class date is called off (#1207). After "Call off dates" on Sessions → Month dates, a "Credits for the dates you called off" card lists each date with how many families were credited and the total. It also says plainly when a family got nothing, for example "the month's free extra class covered it" or "not invoiced yet". The cancel response gained `credit_total_cents` and `credit_skips` for this; no new endpoint.

A family's record → Billing now has a Credits panel: the available balance, then every credit with its reason, amount, what is left, who approved it and which invoice it came off. It is admin-only and reads only that family's credits.

A past date that is still marked as class now offers "Credit as missed" on Month dates, for a closure found out only after the day. The admin gives a reason and previews the families and amounts first; confirming marks the date No class on the parent calendar, does not pay the coach, and issues the same credit a call-off would (same amount to the cent, same per-date credit key, so it can never be issued twice by either path). New route `POST /api/v2/admin/session-occurrences/{id}/credit-missed` (admin only, `dry_run` for the preview). It refuses a date with any student marked present or late, a date whose attendance could not be checked, a date that has not finished yet, a date already called off, and a date the month's billing never laid out because the schedule was edited after it (the preview says so; credit those families by hand). No email goes to families.

Credits now only give back money that was collected, on every cancel path including the existing call-off. A child billed as NoCharge or Waived is not credited ("free tuition") unless that month was actually invoiced: a child marked not billed after paying keeps the credit. A family with no invoice or billing snapshot for a month that is already over is not credited from the class fee ("not invoiced for that month"). Both show by name in the missed-class preview with that reason.

The family Credits panel shows a pending or expired credit as such; only an approved credit with money left reads as available.

## Deploy notes
- No migration and no new setting. Credit idempotency relies on the existing unique credit source index from migration 0168.
- If the coach's payout period covering the date is already approved or paid, the credit still goes through and the page shows a note to adjust that coach's pay by hand; the lifecycle event records `payroll_flag`. A draft payout period covering the date is flagged too: recompute that coach's draft payout before approving it.

## Risk / rollback
- Risk: crediting a missed date moves money (a credit on the next invoice). The preview is a dry run that writes nothing; the confirm needs a reason and records the admin on the credit and the lifecycle event.
- Risk: a frozen payout is flagged, not reversed, so payroll needs a manual adjustment for that date.
- Rollback: revert the PR. Credits already issued stay in the ledger as ordinary class-cancellation credits and still apply to the next invoice.
