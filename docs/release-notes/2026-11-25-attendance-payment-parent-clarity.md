# Attendance, payment, and Parent schedule clarity

PR: TBD

## What changed
Admin attendance shows the dated class and links to its record. Paid Collections separates the family total from individual invoice allocations and opens the linked invoice. Parent child cards label the next class, show schedule loading and retry states, and link directly to the child's coach notes.

## Deploy notes
None.

## Risk / rollback
The read views add optional class metadata and invoice allocation details. Revert this change if those views regress. Attendance rules, invoice calculations, and stored data are unaffected.
