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

Not changed here: the underlying attendance-conflict/not-enrolled data cases
themselves (see #517 for the correction workflow and the linked incident issue
for the per-student investigation).

## Deploy notes
No migration, no config. Safe to deploy immediately; both changes are
backward-compatible (422 replaces a 500; messages/logging only).

After deploy, if a coach still cannot mark a specific student, run
`fly logs -a courtmastr-academy-api --no-tail | grep domain_error` — the line
carries the `Coaching.*` code plus `student_id`/`occurrence_id`.

## Risk / rollback
Low. The backend change narrows accepted input on one coach endpoint to the set
the use case already enforced; the only behavioural difference is 422 vs 500.
Rollback is a revert of this PR.
