# admin-occurrence-attendance-scope

PR: TBD

## What changed
Admin → Sessions → class → Class dates now shows the Attendance action for a date the coach has marked in any academy, not only the primary one. The class-date row counted attendance marks against the academy the server booted with (`primary_academy_id` / `default_academy_id`), so every other academy (the Demo Academy included) saw 0 marks and no Attendance action, and with colliding occurrence ids could see the boot academy's count instead. The count, the marked-by coaches and the last-marked time now come from the requesting academy. Dates with no marks still show no Attendance action. The admin user list (`ListAdminUsers` / `MongoUserRepository.list_users`) now requires an academy id instead of falling back to the boot academy when one is omitted; every caller already passed it.

## Deploy notes
None. No migration, env var or manual step. `GET /admin/sessions/{session_id}/occurrences` keeps its shape; only the `attendance_marked_*` values change for non-primary academies.

## Risk / rollback
One query filter changes from the boot academy to the request academy (`request_academy_id()`, which fails closed in multi-academy mode and keeps the single-academy fallback). The primary academy's rows read exactly as before. Covered by a real-Mongo contract test that boots as one academy and reads as another. Roll back by reverting the PR.
