# batch-1: registration review merge

PR: #0

## What changed
- Fixes #755 — admin registration approve/waitlist built a brand-new `Student()` from the incoming application and handed it to `MongoStudentWriter.upsert`, whose blanket `$set` nulled `date_of_birth`, `emergency_contact_name`/`phone`, `medical_notes`, and `student_user_id` on an already-existing student. This wiped values a parent had set via self-service and dropped the migration-0150 login link (#610). Both approve and waitlist call sites now merge onto the existing student record via a new `_merged_student` helper backed by `StudentRegistrationQuery.get_by_id`, only overwriting a field when the incoming application value is non-blank.

## Deploy notes
No migration required. No manual env var or manual step needed before merge — this is a pure application-layer bug fix (composition + infrastructure read/write paths only).

## Risk / rollback
Risk: registration approve/waitlist now performs an extra read (`StudentRegistrationQuery.get_by_id`) before writing; this only affects the admin registration review flow and is covered by new unit tests in `test_admin_registration_review.py`. If this regresses, revert the merge commit for this PR — no data migration or backfill is entangled with the change.
