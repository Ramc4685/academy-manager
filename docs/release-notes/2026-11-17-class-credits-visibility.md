# class-credits-visibility

PR: TBD

## What changed
Owners can now see the credits families get when a class date is called off (#1207). After "Call off dates" on Sessions → Month dates, a "Credits for the dates you called off" card lists each date with how many families were credited and the total. It also says plainly when a family got nothing, for example "the month's free extra class covered it" or "not invoiced yet". The cancel response gained `credit_total_cents` and `credit_skips` for this; no new endpoint.

A family's record → Billing now has a Credits panel: the available balance, then every credit with its reason, amount, what is left, who approved it and which invoice it came off. It is admin-only and reads only that family's credits.

A past date that is still marked as class now offers "Credit as missed" on Month dates, for a closure found out only after the day. The admin gives a reason and previews the families and amounts first; confirming marks the date No class on the parent calendar, does not pay the coach, and issues the same credit a call-off would (same amount to the cent, same per-date credit key, so it can never be issued twice by either path). New route `POST /api/v2/admin/session-occurrences/{id}/credit-missed` (admin only, `dry_run` for the preview). It refuses a date with any student marked present or late, a date whose attendance could not be checked, a future date and a date already called off. No email goes to families.

## Deploy notes
- No migration and no new setting. Credit idempotency relies on the existing unique credit source index from migration 0168.
- If the coach's payout period covering the date is already approved or paid, the credit still goes through and the page shows a note to adjust that coach's pay by hand; the lifecycle event records `payroll_flag`.

## Risk / rollback
- Risk: crediting a missed date moves money (a credit on the next invoice). The preview is a dry run that writes nothing; the confirm needs a reason and records the admin on the credit and the lifecycle event.
- Risk: a frozen payout is flagged, not reversed, so payroll needs a manual adjustment for that date.
- Rollback: revert the PR. Credits already issued stay in the ledger as ordinary class-cancellation credits and still apply to the next invoice.
