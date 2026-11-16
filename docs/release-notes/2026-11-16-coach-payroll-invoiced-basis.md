# coach-payroll-invoiced-basis

PR: TBD

## What changed
Coaches on a percent-of-revenue rate are now paid a share of the tuition actually invoiced for each class and academy-local month. Before, the base was the class fee times the class's active enrollments on the day payroll ran, so a family dropping on the 25th re-priced classes the coach had already taught.

- The base per class and month is the sum of its invoices that are not draft, void or deleted: tuition and discount lines (so a sibling discount nets in), less any header-only discount, floored at $0. ACH discount, account credit (including referral credit), late fees, move proration, self-cancel fees and adjustments stay out. A registration checkout's paid first month counts once, never on top of an invoice for the same family and class-month.
- Each class in the month gets an equal share, in whole cents that add up to the month's tuition exactly. The month is the academy's local month, so a Saturday 7pm class on Oct 31 counts in October.
- A class-month with no invoices gives a percent coach a blocking warning ("No invoiced tuition"), unless the owner chooses to pay $0 for it.
- Owner settings under Settings > Billing rules > Coach payroll: whether the ACH discount reduces the base (off), whether checkout first months count (on), how cancelled classes split the month (classes that ran, or every scheduled class), and whether an uninvoiced class-month blocks approval or pays $0 (block). Changes are audited and apply to periods generated or recomputed afterwards.
- Approval is refused until the month is over and the period was calculated after it ended on the invoiced basis. A mid-month period is a preview ("Preview. Approve unlocks after Oct 31."), and stale or legacy drafts show a Recompute prompt.
- Assistants listed on a class are paid their own line at their per-session or per-hour rate (or an attendance override), unless marked absent. A percent rate or a missing rate on an assistant blocks approval (set a $0 rate for a volunteer). Assistants appear in the monthly payroll list, the Assistant chip and both Excel exports.
- Payout period writes check the status they loaded: a reopen racing a mark-paid gives the loser a 409 and the stored period is unchanged. Mark-paid stores any amount; the period flags a paid amount that differs from the total.
- The Payslips tab reads the picked month from the monthly payroll list. The old derived payouts list (`GET /admin/finance/payouts`) and its students and expected-revenue tiles are removed.

## Deploy notes
- No migration, no backfill, no new env var. Settings default to the values above until the owner changes them.
- Approved and paid periods are never recomputed and keep the amounts they were approved at.
- Existing drafts carry no revenue basis and read as the legacy expected-revenue basis: recompute each one (or use Recompute month on Coach Payroll) before approving it.
- Owner checks after deploy: open the current month on Coach Payroll and see the preview banner on a draft; recompute last month and check a percent coach's lines read "% of invoiced tuition"; any class-month without invoices shows the blocking warning.

## Risk / rollback
- Risk: a percent coach's pay changes for any recomputed month, because the base moves from projected to invoiced tuition. Classes moved mid-month count the whole month for the destination class (known shortcut).
- Rollback: revert the PR. Periods recomputed under this change keep their stored lines and `revenue_basis: "invoiced"`, which the old code ignores; the four settings fields stay on the billing settings document unused.
