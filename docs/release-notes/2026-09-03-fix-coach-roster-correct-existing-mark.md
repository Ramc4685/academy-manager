# fix-coach-roster-correct-existing-mark

PR: #653

## What changed
Closes #646. After #639/#643 a student's existing mark renders correctly, but
tapping the *other* button to change it (Absent → Present) still failed with
"Attendance for this student was already recorded": the roster buttons only
ever created a new mark (`POST /coach/attendance`), which is write-once, so
every change 409'd. The correction endpoint from #517
(`PATCH /coach/occurrences/{occurrence_id}/attendance/{student_id}`, coach
48h window, supervisors unlimited) existed but nothing in the coach UI called it.

Frontend only — no backend change:

- `frontend/lib/api/coach.ts`: `correctAttendance(occurrenceId, studentId,
  {status, reason})` client for the PATCH.
- `frontend/app/(coach)/coach/sessions/[id]/page.tsx`:
  - Tapping a status when a mark already exists (hydrated or just saved) now
    calls the correction; tapping the same status is a no-op.
  - A `Coaching.ConflictAttendanceExists` on a plain mark (mark exists but the
    page didn't know) is automatically retried as a correction instead of
    surfacing an error.
  - New messages for `Coaching.CorrectionWindowExpired` ("older than 48 hours —
    admin only") and `Coaching.AttendanceNotFound`.
- e2e: `coach-today.spec.ts` conflict case now asserts the PATCH is sent and
  the row shows the new status with no error; `mock-api.ts` gains the PATCH
  route + `correctionCalls`.

Also fixes #650 (blocking the local push gate): `admin-shell.spec.ts` "shells
expose logout" failed deterministically on WebKit because the persona auth
hook's `replaceLocation` arms a 1s hard `window.location.replace("/login")`
fallback, and that timer from the previous persona's page interrupted the next
persona's `page.goto`. Each persona now runs in its own page.

## Deploy notes
None. Frontend deploy only; the backend correction endpoint is already live.
Coaches can change a mark within 48h of it being recorded; admins/owners in
Coach view can change any mark.

## Risk / rollback
Low. Only the roster tap routing changed; first-time marks still use the
existing POST. Rollback is a revert of this PR.
