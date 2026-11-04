# fix-readd-dropped-student-legacy-index

PR: #835

## What changed

- Admins can again re-add a student to a class they were previously dropped from. The add failed with "Could not add <name> — a conflicting record already exists for this student", pointing the admin at an enrollment that was already gone.
- Root cause was a leftover database index, not application logic: production `enrollments` carried an auto-named full unique index on `(session_id, student_id)` that no migration creates. It counted ended rows, so a single `dropped` enrollment blocked every later enrollment row for that student in that class. The application rule has always been that only a live enrollment (active, paused, held) blocks an add.
- New migration `0184_drop_legacy_session_student_unique` removes that index wherever it exists (matched by key, not name; safe to re-run). Duplicate-live-enrollment protection is unchanged — it stays in the roster pre-checks.
- Backend-only: one migration and its tests. No API, frontend or behaviour change beyond the unblocked re-add.

## Deploy notes

Migrations do not run on boot in production (#629): after the backend deploy, apply `0184` by hand via `fly ssh console -a courtmastr-academy-api` and `backend.v2.migrations.run_pending_migrations`. The index was already dropped by hand on production on 2026-09-20 to unblock the affected family, so there the migration is a no-op that only records itself. No env vars.

## Risk / rollback

Low. Dropping an index changes no data, and lookups by session or student remain covered by `roster_by_session` and `enrollments_for_student`. The dropped index was never relied on by the code — the use cases enforce "one live enrollment per student per class" themselves. To roll back, revert this PR's merge commit; the index should NOT be recreated, since it reintroduces the defect.
