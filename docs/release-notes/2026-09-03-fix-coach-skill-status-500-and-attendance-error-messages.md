# fix-coach-skill-status-500-and-attendance-error-messages

PR: #639

## What changed
Two coach-view failures reported from production on 2026-09-03, minutes before
sessions:

**1. Skill Passport status change → "Something went wrong — Internal Server
Error" (500).** Prod logs showed the cause directly:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for UpdateSkillStatusCommand
Input should be 'INTRODUCED', 'LEARNING', 'PRACTICING', 'TEST_READY' or 'NEEDS_REVIEW'
[type=literal_error, input_value='PASSED', input_type=str]
```

The passport dropdown offered **Passed** (and Not started), but the backend's
`CoachSettableStatus` deliberately excludes them — a skill is passed only through
"Record test". The route body typed `status` as a bare `str`, so nothing rejected
the value at the edge; the Literal blew up while constructing the command inside
the handler, which is a 500.

- `backend/v2/interfaces/coach/skill_routes.py`: `UpdateStatusBody.status` is now
  `CoachSettableStatus`, so an unsupported value is a 422 listing the allowed
  values, and the use case is never invoked.
- `frontend/app/(coach)/coach/students/[studentId]/passport/page.tsx`: the
  dropdown lists only coach-settable statuses; a current Not started / Passed
  value stays visible as a disabled option; a failed update now shows the server
  message plus "Use Record test to mark a skill as passed" instead of nothing.
- Regression test: `test_real_skill_router_rejects_non_coach_settable_status_with_422`
  (PASSED / NOT_STARTED / arbitrary string → 422, spy never called).

**2. Attendance: some students save, others show "Could not save attendance.
Check your connection and retry."** Every non-404 failure — including the three
legitimate 409 domain rejections (`Coaching.ConflictAttendanceExists`,
`Coaching.StudentNotEnrolled`, `Coaching.SessionNotAssigned`) — was rendered as
a connectivity problem, so a coach could not tell "already marked on another
device" from "this student isn't actively enrolled" from "no signal". Worse, the
`DomainError` exception handler wrote nothing to the log, so these rejections
were invisible in production and the report could not be diagnosed after the
fact.

- `backend/v2/shared/http/errors.py`: the domain-error handler now logs one
  structured WARNING per rejection (`method path -> status code details=…`), so
  `fly logs | grep domain_error` shows exactly which student/occurrence was
  rejected and why.
- `frontend/app/(coach)/coach/sessions/[id]/page.tsx`: `formatApiError` maps each
  domain code to an actionable message, keeps the connectivity wording only for
  actual network failures, and distinguishes 5xx.

**3. Root cause of "some students can't be marked" — a v1 unique index left on
prod.** With the new logging live, the rejections read
`Coaching.ConflictAttendanceExists` with `existing_attendance_id: None`: the
unique-index collision was on a key the tenant-scoped lookup never checks.
Prod still carries the v1 index `session_id_1_student_id_1_date_1`
(session_id, student_id, date). v2 rows never set `date`, so for a recurring
session every v2 row collapses to `(session_id, student_id, null)` — **a
student marked once in a session can never be marked again in it.** Confirmed
against prod data: all 15 students marked on the 2026-09-02 occurrence had
zero earlier v2 rows for the session; the single student with an earlier row
(2026-06-10) was the one the coach could not mark. Left alone, every student
marked this week would have failed next week.

- `backend/v2/migrations/0164_drop_legacy_attendance_session_date_index.py`
  drops the v1 index. Integrity stays enforced by `attendance_occurrence_unique`
  (academy_id, occurrence_id, student_id) from migration 0081.
- Coach session page: an "already recorded" conflict re-hydrates from the
  server and no longer blanks the row, so the existing mark stays visible next
  to the message (the second symptom: Diya/Anjana *were* marked; a re-tap
  hid the mark).

## Deploy notes
No config. Migration 0164 drops one legacy index; boot-time migrations are
OFF in prod (`V2_RUN_MIGRATIONS_ON_BOOT=false`, #629), so apply it by hand
(or drop `session_id_1_student_id_1_date_1` on `attendance` directly) — the
attendance fix is not live until that index is gone. Everything else is
backward-compatible (422 replaces a 500; messages/logging only).

After deploy, if a coach still cannot mark a specific student, run
`fly logs -a courtmastr-academy-api --no-tail | grep domain_error` — the line
carries the `Coaching.*` code plus `student_id`/`occurrence_id`.

## Risk / rollback
Low. The backend change narrows accepted input on one coach endpoint to the set
the use case already enforced; the only behavioural difference is 422 vs 500.
Rollback is a revert of this PR.
