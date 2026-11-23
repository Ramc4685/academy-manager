# admin-attendance-inbox

PR: #1230

## What changed
The Admin Inbox has a new Attendance tab. It lists class dates from the last 30 days that had students on the roster but no attendance marks once the coach's 48-hour window passed (a date whose marks were all voided counts as a correction, not as missing) (these feed the Inbox badge and a "Attendance not taken" card on the dashboard), and marks corrected or voided in the last 14 days for review. A missing date opens the coach marking screen for that class (`/coach/sessions/<occurrence>?date=<academy-local date>`), where an admin marks as a coach supervisor; a correction opens that class date with its Attendance dialog open (`/admin/sessions/<id>?tab=dates&occurrence=<id>`).

## Deploy notes
None. No migration, env var or manual step. The query reads existing `session_occurrences`, `attendance`, `enrollments`, `sessions` and `students` through request-scoped tenant context.

## Risk / rollback
Read-only. If counts look wrong, the Inbox badge and dashboard card over- or under-report attendance work; nothing is written. A failing read shows the tab as "Could not count" instead of zero. Roll back by reverting the PR.
