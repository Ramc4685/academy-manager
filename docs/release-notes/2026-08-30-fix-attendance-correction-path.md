# attendance-correction-path

PR: #579

## What changed
Student attendance was write-once: a second mark for the same
(occurrence, student) 409s with `ConflictAttendanceExists`, and no coach or
admin endpoint could update an existing row — a mis-tapped "present" was
permanent short of manual Mongo edits, and the wrong mark fed parent-visible
activity, absence gating, and attendance reporting.

A new `CorrectAttendance` use case in the coaching context adds an explicit
correction path without loosening the conflict rule:

- Coach: `PATCH /api/v2/coach/occurrences/{occurrence_id}/attendance/{student_id}`,
  allowed within a 48h grace window from the original mark and only for a
  coach assigned to the occurrence. Outside the window:
  `Coaching.CorrectionWindowExpired` (403).
- Admin: `PATCH /api/v2/admin/session-occurrences/{occurrence_id}/attendance/{student_id}`,
  allowed any time.
- Every correction stamps an audit trail on the row (`corrected_by`,
  `corrected_at`, `previous_status`, `correction_reason`) and emits a
  `Coaching.AttendanceCorrected` outbox event. Correcting to the current
  status is a no-op (no write, no event).

Product-layer UX for surfacing the correction controls is tracked separately
as #554.

## Deploy notes
No migration. Corrections update the existing attendance row in place by
`attendance_id` under the tenant scope; the audit-trail fields are new
optional document fields read with `.get()`, so existing rows need no
backfill.

## Risk / rollback
Low. The mark path is untouched (same conflict rule, same unique index); the
new PATCH routes are additive and fail closed (404 when no mark exists, 403
outside the coach window). Rollback is a plain revert — rows already
corrected keep their new status plus audit fields, which older code ignores.
