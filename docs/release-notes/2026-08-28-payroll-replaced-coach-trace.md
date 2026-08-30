# payroll-replaced-coach-trace

PR: #485

## What changed
When a substitute coach was recorded on a session occurrence (`actual_coach_id`
different from `scheduled_coach_id`), the originally scheduled coach's
occurrence vanished from their payout statement entirely — not paid, not
unpaid, not absent, not excluded — so a mistaken substitute attribution
removed pay with nothing for an admin to review. The substitute is still paid
as before; the displaced scheduled coach now gets an explicit
`replaced_by_actual_coach` row naming the coach the session was attributed to,
visible in the payout review table and the XLSX export. The row is
non-blocking (like an attendance override), so it does not stop approval and
does not change payout totals. Payroll generation now also creates a period
for a displaced coach who has no other work that month, with a session count
of 0 so the session is not double-counted.

## Deploy notes
None. No migration, no env vars. `payout_periods` documents gain an optional
`attributed_coach_id` on existing `unpaid_occurrences` entries; documents
written before this change hydrate with `None`.

## Risk / rollback
Payout amounts and totals are unaffected — only non-pay audit rows are added.
The visible change is extra "Replaced" rows in the payout session log and, for
months containing a substitution, one extra $0 payout period per displaced
coach in the monthly payroll list. Revert the PR to restore the previous
behaviour; no data cleanup is required, since the added rows are descriptive.
