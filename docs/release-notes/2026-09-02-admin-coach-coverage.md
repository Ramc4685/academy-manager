# admin-coach-coverage

PR: #633

## What changed
- Academy admins and owners can now switch to the **Coach view** (the
  persona switcher offers it even without the coach role) and see every
  session in the academy on Today and Sessions, each labelled with the
  coach's name.
- From that view they can open any session and use the coach screens as
  the coach would: mark, bulk-mark and correct attendance, view the
  roster, add progress notes and lesson plans, post announcements, and
  use the skills board and teaching plan. Marks are recorded under the
  admin's own name; corrections take the admin path (no 48-hour window).
- Coach routes now admit `admin` / `owner` claims alongside `coach`.
  Parents and students still get 404 on every coach route, and platform
  roles do not qualify. Coaches' own view is unchanged.
- The coach shell shows an "Admin coverage" banner for supervisors.
- `GET /coach/today` and `GET /coach/sessions` responses gain two nullable
  fields, `coach_id` and `coach_name`.

## Deploy notes
No migration, no new env vars, no data change. Effective for every
academy immediately after deploy; an owner/admin only needs to open the
persona switcher and pick "Coach view".

## Risk / rollback
Low. The guard change is additive (it widens who may enter the coach
BFF; it never narrows), the academy-wide queries are only reached by
admin/owner claims, and the assignment override runs after the
tenant-scoped session lookup so it cannot cross academies. Attendance
validation (occurrence, cancellation, enrollment, conflict, idempotency)
is untouched. Rollback is reverting the PR.
