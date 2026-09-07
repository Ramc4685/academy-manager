# fix-coach-makeup-attendance

PR: #TBD

## What changed
Coaches can now mark attendance for the MAKE-UP and TRIAL rows the occurrence roster
already shows (issue #672). Both attendance writes required an `active` enrollment in the
session, which a make-up attendee never has, so "Mark all present" 422'd the whole batch
and the single tap 409'd. `contexts/coaching/application/ports.py` gains an
occurrence-aware `EnrollmentLookup.attendance_eligibility`, adapted in
`composition/coaching_lookups.py` from an active enrollment (session or recurring
template, unchanged fallback) OR an approved one-time `OccurrenceRosterEntry` for exactly
that occurrence. Paused, withdrawn and cancelled enrollments stay ineligible.

A `makeup` roster row additionally requires the student to still hold an active-or-paused
enrollment somewhere in the academy (`MongoEnrollmentRepository.active_or_paused_for_student`,
reached through the new `EnrollmentEligibilityReads` protocol in
`composition/coaching_lookups.py`). Cancel / withdraw only prunes one-time rows on the
*cancelled* session and a make-up targets a different session by construction, so an
approved row can outlive the family's exit; without this check it would still earn
attendance. `trial` rows have no enrollment by definition and stay eligible.
`BulkMarkAttendance` validates every row first and the 422
`Coaching.BulkStudentNotEnrolled` now carries `details.student_ids`; the coach session page
(`frontend/app/(coach)/coach/sessions/[id]/page.tsx`) shows a banner naming those students,
flags their rows, and leaves them out of the retry instead of failing silently. Attendance
documents and the `Coaching.AttendanceMarked` payload persist `entry_source`
(`enrollment` | `makeup` | `trial`, default `enrollment` on older rows) so reports and
payroll can tell make-up attendance apart.

## Deploy notes
None. No migration: the `attendance` collection has no JSON-schema validator (only the
indexes from migrations 0020/0081), so the new `entry_source` field needs no `collMod`.
No env vars, no new routes; the two attendance routes keep their paths, status codes and
response shapes (only the 422 error `details` gained `student_ids`).

Not in this PR: marking a make-up present does not close the make-up request. The
enrollment context has no "consumed / completed" hook for approved make-ups
(`MakeupRequestStatus` lists `completed` but nothing sets it), so the entitlement stays
`approved` after attendance; a follow-up should add that transition, event-driven from
`Coaching.AttendanceMarked` with `entry_source="makeup"`.

## Risk / rollback
Eligibility widens only by approved roster entries for the same occurrence, the same read
the coach roster renders; anyone the coach could not mark before and who is not on that
roster still cannot be marked. A regression would surface as an unexpected 409/422 on
attendance or an attendance row with the wrong `entry_source`; the field is additive and
defaulted, so reverting the PR is safe with rows written in between simply keeping their
`entry_source` value.
