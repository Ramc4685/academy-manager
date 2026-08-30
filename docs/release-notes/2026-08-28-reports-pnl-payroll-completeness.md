# reports-pnl-payroll-completeness

PR: #488

## What changed
The Admin Reports dashboard could show a confident monthly net profit while
coach payroll was only partly generated — one coach ungenerated, or periods
still in draft — because only the zero-payroll case was guarded. P&L is now
either accurate or explicitly blocked through the same `payroll.blocked_by`
banner: net profit, margin and coach payroll go null and the banner names each
reason (coaches with no payout period, draft periods, periods with unresolved
pay issues, periods not covering the full month). Estimated/approved/paid
payroll stay visible for preview. A complete month computes P&L from the
payroll obligation (approved + paid), and the Reports page now shows the
blocking reason next to Net profit instead of a bare "No data".

## Deploy notes
None. No migration, no env vars, no API shape change.

## Risk / rollback
Owners will see net profit blocked for any month whose payroll is not fully
generated and approved — that is the intended correction, but it will look
like a regression to anyone used to the old number. Two months of behaviour
change to expect: a mixed draft/approved month now blocks instead of quietly
using approved-only payroll, and a month with no payable coach occurrences is
no longer blocked (zero payroll is the accurate answer there). Payout window
matching normalises Mongo's naive datetimes against the timezone-aware month
bounds; without that, every period would read as not covering the month and
P&L would stay blocked. Revert the PR to restore the previous behaviour; no
data changes to undo.
