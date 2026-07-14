# fix-resolve-registration-approval-defects

PR: #302

## What changed
- prevent false admin approval errors and repair registration enrollment dates
- block duplicate child registrations with tenant-scoped matching, fenced review claims, and an atomic registration lock
- show dynamic Child added confirmation instead of Payment received
- keep ambiguous legacy child matches visible for manual review

## Deploy notes
Includes migration(s): backend/v2/migrations/0146_registration_enrollment_dates.py, backend/v2/migrations/0147_registration_student_lock.py. Confirm `V2_RUN_MIGRATIONS_ON_BOOT` covers it or run manually — see AGENTS.md.

## Risk / rollback
_Auto-generated stub — author: fill in what breaks if this is wrong and how
to roll back before merge._ Revert the merge commit if this regresses.
