# fix-enrollment-core-tenant-unique-ids

PR: #874

## What changed

- Migration `0186_enrollment_core_ids_unique_per_academy` replaces four globally-unique id indexes with per-academy ones: `sessions.session_id`, `enrollments.enrollment_id`, `session_occurrences.occurrence_id` and `attendance.attendance_id` are now unique on `(academy_id, <id>)`. This is the first batch of #849 and the same fix migration 0162 made for `students` after #610.
- Nothing changes for users today. Every read and write on these collections was already tenant-scoped; only the database rule disagreed. With a single academy the old rule could not fire. It would have fired as a permanent 500 on enrollment, scheduling or attendance once a second academy was onboarded from imported, copied or restored data that kept its ids.
- Docs with no id stay outside the constraint (`partialFilterExpression` on `$type: "string"`), as before under the old `sparse` indexes.

## Deploy notes

Backend-only. Migrations do not run on boot in production (#629): after the deploy, apply `0186` by hand via `fly ssh console -a courtmastr-academy-api` and `backend.v2.migrations.run_pending_migrations`. It pre-flights all four collections first and aborts without touching any index if one holds a duplicate `(academy_id, <id>)` pair; a read-only check of production on 2026-09-21 found zero duplicates and zero docs without an `academy_id`. Each new index is created before its old one is dropped, so uniqueness is never absent. Afterwards run the drift audit (`--dump` on Fly, `--check` locally) and expect `ok: true`. No env vars.

## Risk / rollback

Low. The largest of the four collections holds about 100 documents, so the index builds are near-instant, and no application code changes. Verified against a real MongoDB as well as the unit tests, because the test fake does not evaluate partial filters. To roll back, revert this PR's merge commit; if `0186` was already applied, the per-academy indexes are strictly more permissive across tenants and equally strict within one, so they are safe to leave in place.
