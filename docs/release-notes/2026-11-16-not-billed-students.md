# not-billed-students

PR: #1198

## What changed
The owner can mark a class "Not billed" (Owner's child, Coach's child, Scholarship, or Other with a note) from the student Sessions panel or the family Billing tab, and "Start billing" again later. Marking writes the importer's existing `NoCharge` billing type, so the monthly run, the sibling discount and the billed-students count treat it like an imported no-charge class. It takes effect going forward, is recorded in the billing audit log, and can optionally void that class's open, unpaid invoices. "Start billing" restores the previous type and skips the current month, so the first new invoice is next month's. The class row shows "Not billed · Owner's child", and the sibling badge reads "not billed (Owner's child)".

Not-billed children stay on rosters, attendance and skills, but leave the headcounts: the Students Active tile, the Families Active/Leaving tiles, the family Enrollments tile, the roster "In session" tile, the at-risk report, the pathway dashboard, projected income and session economics. Each of those shows "+N not billed". Seat counts and capacity still include them.

Coach payroll: a class whose live children are all not billed now has a $0 percent-of-revenue base instead of a blocking "missing invoiced tuition" warning.

## Deploy notes
No migration and no setting. New owner-only route: `PUT /admin/enrollments/{enrollment_id}/billing`. It writes `billing_type`, `not_billed_reason`, `not_billed_note`, `not_billed_by`, `not_billed_at` and `billing_type_before_not_billed` on `enrollments`; "Start billing" adds the current month to `skip_periods`. Existing `NoCharge` and `Waived` rows count as not billed with no reason recorded.

## Risk / rollback
Money path: whether a class is invoiced. A wrong mark is undone with "Start billing", which is audited. Reverting the PR leaves rows marked `NoCharge`, which the monthly run already skipped before this change. A voided invoice stays void, as with any void. Covered by real-Mongo tests for the run skip and restart, the payroll warning, the audit row and the headcounts.
