# feat-student-past-enrollments

PR: #677

## What changed
The admin student page (`/admin/students/[studentId]`, Sessions tab) now shows a
**Past enrollments** section — cancelled and withdrawn enrollments with the session,
when it ended (`cancelled_at` for cancels, `withdrawal_date` for withdrawals), who
ended it (`cancelled_by`) and the recorded reason — so a cancelled student no longer
looks like one who was never enrolled (issue #674, follow-up to #651). A transfer
moves the enrollment row in place with no status change, so it never produces a past
row; `transferred_out` was dropped from the read, the chip labels and the fixtures.
Each current enrollment row also carries an **Autopay** chip that links to the family
billing page where autopay is managed, using the same three words that page uses:
"Autopay" (active), "Autopay off" (paused), "Manual" for everything else including
billing's default `not_offered`, a merely `offered` setup and a missing billing
record. Only `setup_started` reads as "Autopay pending".

The ended date is rendered with the midnight-UTC heuristic already used for invoice
dates (`formatInvoiceDate`) for every past row regardless of status: admin cancel and
withdraw both stamp `_start_of_day_utc(effective_date)`, so a 9/1 cancel used to read
as 8/31 for a viewer in a US timezone.

Cancel and withdraw now stamp `cancelled_by` and `cancellation_reason` on the
enrollment document (`_persist_lifecycle_dates` → `MongoEnrollmentWriter.
set_lifecycle_dates`), not only on the lifecycle event. Without this the "Ended by"
and "Reason" columns were blank for every admin-initiated cancel and every
withdrawal, since the past read takes those facts off the enrollment doc. The
class-wide session cancel stamps the same `session_cancelled` reason it already
records on the event.

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
working against the new API and vice versa. The two new enrollment fields
(`cancelled_by`, `cancellation_reason`) need no validator change: the `enrollments`
validator in migration 0132 lists properties without `additionalProperties: false`,
and `cancelled_by` / `cancellation_reason` were already written by existing paths.
Existing enrollments cancelled before this change keep blank actor/reason columns —
they are not backfilled.

## Risk / rollback
The read path is read-only; the one write change is the extra `cancelled_by` /
`cancellation_reason` `$set` on cancel and withdraw, which adds no new document and
cannot fail a validator. The existing endpoint does two extra reads per student-detail
request (one enrollment query for past rows, one billing query for autopay). If
billing has no record for an enrollment the chip reads "Manual" rather than inventing
a state. Rollback is reverting the PR; the stamped actor/reason fields are inert for
older code and need no data undo.
