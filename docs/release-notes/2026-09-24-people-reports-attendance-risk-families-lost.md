# People reports: attendance risk by class and coach, families lost and why

PR: TBD

## What changed
- `/admin/reports` "People" group gains two cards, both plain tables with empty states.
- Attendance risk by class and coach (`GET /api/v2/admin/reports/people/attendance-risk`): students whose lifecycle is at risk (no attendance in their class's last three class dates, voided marks excluded), counted per class and per the class's scheduled coach. It reuses the enrollment context's lifecycle derivation, the same rule as the Students page's At risk tab, so the two cannot disagree. A student in two classes counts in each class and once per coach.
- Families lost and why (`GET /api/v2/admin/reports/people/families-lost?from=&to=`): families whose children have all left (the Families view's Left stage) with a departure that took effect in the window (academy-local days, default the last 90). Each family is counted under the latest structured leaving reason recorded in the Drop or Stop-all-classes dialog (#775). If no reason was recorded, it is counted by how its last class ended (dropped by staff, cancelled by the family, hold ran out, and so on), and the card says so.
- Neither card shows money. Both are admin-visible and are not owner-only.

## Deploy notes
- None. No migrations: departures are read on the existing `enrollment_event_type_effective` index (0090). No env vars, no owner steps. Read-only.

## Risk / rollback
- Low. Two new read-only admin routes and two cards. A wrong number is a display problem only. Nothing writes.
- The attendance risk card runs the academy-wide lifecycle derivation once per request, the same batched reads the Families view already makes.
- Rollback: revert this PR and redeploy backend and frontend.
