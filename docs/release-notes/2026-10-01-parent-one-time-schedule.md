# Parent: show approved make-ups and trials on schedules

PR: #1048

## What changed

- Approved make-ups and trials were on the coach roster but missing from the parent's Children schedule, Calendar and Home next-class card. The parent schedule now merges regular enrollments with one-time roster entries, deduplicated per occurrence and labelled Make-up/Trial (#1038).
- Approved make-up and trial requests now show the assigned class, academy-local time and venue on Requests. Existing-child trial cards show the child's name.
- Reads are tenant-scoped and ownership-checked before any roster query. No charges, enrollments or student records are created.

## Deploy notes

- None. No migration, env var or manual step. Optional later: an `(academy_id, student_id)` index on `occurrence_roster_entries` if the collection grows.

## Risk / rollback

- Low. Response DTOs gain optional fields (`source`, `assigned_class`); existing clients ignore them. Assigned-class lookup is best-effort and never fails the page. Rollback: revert the PR.
