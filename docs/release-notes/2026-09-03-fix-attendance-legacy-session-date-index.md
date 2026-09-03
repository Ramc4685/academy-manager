# fix-attendance-legacy-session-date-index

PR: #TBD

## What changed
Root cause of "coaches can mark some students but not others" (#638), found
with the domain-error logging shipped in #639 and confirmed against prod data.

Prod's `attendance` collection still carried the **v1 unique index
`session_id_1_student_id_1_date_1`** (session_id, student_id, date). v2 rows
are keyed by `occurrence_id` and never set `date`, so for a recurring session
every v2 row collapses to the single key `(session_id, student_id, null)` —
**a student marked once in a session can never be marked again in it.** The
rejection surfaced as `Coaching.ConflictAttendanceExists` with
`existing_attendance_id: None`, because the collision was on an index the
tenant-scoped pre-insert lookup never checks.

Prod evidence (2026-09-03): all 15 students marked on the 2026-09-02
occurrence had zero earlier v2 rows for that session; the single student with
an earlier v2 row (2026-06-10) was the one the coach could not mark. Left in
place, every student marked this week would have failed next week.

- `backend/v2/migrations/0164_drop_legacy_attendance_session_date_index.py`
  drops the v1 index. Integrity remains enforced by
  `attendance_occurrence_unique` (academy_id, occurrence_id, student_id) from
  migration 0081. The 8 remaining v1-shaped rows (which do carry `date`) are
  untouched.
- `frontend/app/(coach)/coach/sessions/[id]/page.tsx`: an "already recorded"
  conflict now re-hydrates from the server, and a failed local attempt no
  longer masks the server's existing mark — the second symptom, where students
  who *were* marked showed as blank after a re-tap.

## Deploy notes
Migration 0164 drops one legacy index. Boot-time migrations are OFF in prod
(`V2_RUN_MIGRATIONS_ON_BOOT=false`, #629), so **apply 0164 by hand (or drop
`session_id_1_student_id_1_date_1` on `attendance` directly)** — the attendance
fix is not live until that index is gone. No other config; the UI change is
backward-compatible.

Verify afterwards: mark the previously-blocked student; `fly logs | grep
domain_error` should show no `ConflictAttendanceExists` for a fresh mark.

## Risk / rollback
Low. Dropping a redundant unique index cannot lose data; the v2 uniqueness
guarantee is unchanged. Rollback is re-creating the index (not recommended —
it reintroduces the bug) and reverting the UI commit.
