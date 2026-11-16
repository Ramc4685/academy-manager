# sibling-visibility

PR: TBD

## What changed
Sibling families are marked whatever the billing says: a "Siblings · N" chip on the Families list and the family header (two or more children with an active, held or paused class), and "Sibling of <name>" links on the student page. With the sibling discount on and two or more children on active or paused classes, the badge no longer goes blank: a month already invoiced without the discount previews next month ("From December: …"), and a class the monthly run does not invoice says why (marked No charge, tuition waived, paused, deferred, no class fee …). The family Billing tab always shows a sibling line for such a family.

## Deploy notes
None. No migration, no setting. `GET /admin/families/{id}/sibling-discount` gains `next_period`, `exclusion` and `billing_type`; the family index row gains `sibling_student_ids`. Both are read-only; billing math and who qualifies are unchanged.

## Risk / rollback
Display only. If a label is wrong, revert this PR; no data is written or needs undoing. The monthly run's family filter moved into one shared helper (`_family_exclusion`) with the same checks in the same order, covered by the existing sibling real-Mongo tests.
