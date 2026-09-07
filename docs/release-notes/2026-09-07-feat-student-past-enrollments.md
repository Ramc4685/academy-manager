# feat-student-past-enrollments

PR: #TBD

## What changed
The admin student page (`/admin/students/[studentId]`, Sessions tab) now shows a
**Past enrollments** section — cancelled, withdrawn and transferred-out enrollments
with the session, when it ended (`cancelled_at` for cancels, `withdrawal_date` for
withdrawals), who ended it (`cancelled_by`) and the recorded reason — so a cancelled
student no longer looks like one who was never enrolled (issue #674, follow-up to
#651). Each current enrollment row also carries an **Autopay** chip (on / paused /
off / pending / none) that links to the family billing page where autopay is managed.

Backend: `GET /api/v2/admin/students/{student_id}` gains `past_enrollments` (same
row shape as `enrolled_sessions` plus `cancelled_at`, `withdrawal_date`, `ended_at`,
`cancelled_by`, `reason`) and `autopay_status` on each current row. The past read is
`_admin_student_past_enrollments` in
`contexts/enrollment/infrastructure/mongo_student_repo.py` (soft-deleted rows excluded,
newest ended first; the active+paused read is untouched). Autopay comes from billing's
`student_billing_enrollments.autopay_enrollment_status` through a new Enrollment port
`EnrollmentAutopayLookup`, adapted in the new `composition/student_autopay.py` onto
`MongoStudentBillingEnrollmentRepository.autopay_status_by_enrollment` — no
cross-context Mongo access, and `composition/admin.py` stays at 4751 lines.

## Deploy notes
None. No migration, no new env vars, no new route (the audit inventory manifest is
unchanged). The response fields are additive with defaults, so an older frontend keeps
working against the new API and vice versa.

## Risk / rollback
Read-only: nothing here writes to enrollments or billing. The only behavioural change
to the existing endpoint is two extra reads per student-detail request (one enrollment
query for past rows, one billing query for autopay). If billing has no record for an
enrollment the chip reads "No autopay" rather than inventing a state. Rollback is
reverting the PR; no data changes to undo.
