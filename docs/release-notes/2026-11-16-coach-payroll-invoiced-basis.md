# coach-payroll-invoiced-basis

PR: #1192

## What changed
Coaches on a percent-of-revenue rate are now paid a share of the tuition actually invoiced for each class and academy-local month. Before, the base was the class fee times the class's active enrollments on the day payroll ran, so a family dropping on the 25th re-priced classes the coach had already taught.

- The base per class and month is the sum of its invoices that are not draft, void or deleted: tuition and discount lines (so a sibling discount nets in), less any header-only discount, less the invoice's refunds, floored at $0. ACH discount, account credit (including referral credit), late fees, move proration, self-cancel fees and adjustments stay out.
- Each invoice belongs to the class it billed, read from the billing snapshot stamped when that month was invoiced (the enrollment's current class only when there is no snapshot). A kid who moves classes on Nov 3 leaves October with the old class.
- A registration checkout's paid first month counts, less its refunds, only when its application became an enrollment that still exists (a rejected or never-approved application's payment does not count). It counts once per enrollment, never on top of an invoice for the same enrollment and class-month, so a sibling's first month is not dropped.
- A manual invoice with tuition but no enrollment names no class, so it is in no coach's base. A percent coach's period shows a non-blocking note with how many there were that month.
- Each class in the month gets an equal share, in whole cents that add up to the month's tuition exactly. The month is the academy's local month, so a Saturday 7pm class on Oct 31 counts in October.
- A class-month with no invoices gives a percent coach a blocking warning ("No invoiced tuition"), unless the owner chooses to pay $0 for it.
- Owner settings under Settings > Billing rules > Coach payroll: whether the ACH discount reduces the base (off), whether checkout first months count (on), how cancelled classes split the month (classes that ran, or every scheduled class), and whether an uninvoiced class-month blocks approval or pays $0 (block), and the first month assistants are paid in the app (empty: assistants are paid outside the app; a newly set month cannot be earlier than the academy's current month). Changes are owner-only, audited, and apply to periods generated or recomputed afterwards. The coach payroll save writes only its own fields, so it and a stale billing-rules or ACH save never revert each other.
- Approval is refused until the month is over and the period was calculated after it ended on the invoiced basis. A mid-month period is a preview ("Preview. Approve unlocks after Oct 31."), and stale or legacy drafts show a Recompute prompt.
- From the owner's assistant pay-from month on, assistants listed on a class are paid their own line at their per-session or per-hour rate (or an attendance override), unless marked absent. Before that month assistants get no payroll rows. A percent rate on an assistant blocks approval until the class gets an attendance pay override or the coach a per-session or per-hour rate; a missing rate blocks too. A coach rate can now be set to $0: a volunteer gets a $0 line. A per-session or per-hour rate must name its amount; a request without one is refused rather than saved as $0. Assistants appear in the monthly payroll list, the Assistant chip and both Excel exports.
- Every payout period write checks the version it loaded and bumps it: approve, mark paid, reopen, recompute and line overrides. Of two concurrent writes (an approve racing a recompute, a stale mark-paid after a reopen and re-approval, two recomputes) the loser gets a 409 and the stored period is unchanged. Approve, mark paid and reopen write only their own status and date fields, never the header or lines. Recompute month skips a period that changed under it instead of failing partway. Mark-paid stores any amount; the period flags a paid amount that differs from the total.
- The period export labels the basis column "Expected revenue (legacy)" on a period still on the old basis.
- The Payslips tab reads the picked month from the monthly payroll list. The old derived payouts list (`GET /admin/finance/payouts`) and its students and expected-revenue tiles are removed.

## Deploy notes
- No migration, no backfill, no new env var. Settings default to the values above until the owner changes them. Periods stored before this change have no version and read as version 0.
- Approved and paid periods are never recomputed and keep the amounts they were approved at.
- Existing drafts carry no revenue basis and read as the legacy expected-revenue basis: recompute each one (or use Recompute month on Coach Payroll) before approving it.
- Owner checks after deploy: open the current month on Coach Payroll and see the preview banner on a draft; recompute last month and check a percent coach's lines read "% of invoiced tuition"; any class-month without invoices shows the blocking warning.

## Risk / rollback
- Risk: a percent coach's pay changes for any recomputed month, because the base moves from projected to invoiced tuition. A recompute writes the header and then the lines in two steps; a crash between them leaves stale lines until the next recompute (made atomic in a follow-up).
- Rollback: revert the PR. Periods recomputed under this change keep their stored lines and `revenue_basis: "invoiced"`, and a `version` field, which the old code ignores; the five settings fields stay on the billing settings document unused.
