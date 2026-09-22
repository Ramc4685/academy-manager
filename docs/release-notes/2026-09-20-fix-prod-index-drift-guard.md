# fix-prod-index-drift-guard

PR: #850

## What changed

- New read-only script `backend/scripts/index_drift_audit.py` compares a database's live indexes with what the migrations define. `--dump` runs on the target; `--check live.json` runs locally and exits 1 on a missing index, a changed definition, or a unique index that no migration and no reasoned allowlist entry explains. This is the guard for the class of defect fixed in #835, where a production-only index that the code never knew about blocked re-adding a dropped student.
- A read-only audit of production on 2026-09-20 found no missing and no changed indexes, and nine leftover legacy unique indexes, all inert today. They are recorded in the script's allowlist, each with the reason it is harmless (#836).
- When a roster add is rejected by the database as a duplicate, the backend now logs which index fired (`enrollment.roster_add_duplicate_key`). The admin-facing behaviour is unchanged: the seat is released and the same 409 message is shown. Previously nothing was logged, so Sentry and the Fly logs could not explain the failure.
- Migration `0185_registration_lock_non_terminal` widens the database backstop that stops two concurrent registration approvals enrolling one child twice. It covered `active` and `paused` only; it now covers every non-ended status, including `held`, matching the application checks widened in #782.

## Deploy notes

Backend-only. Migrations do not run on boot in production (#629): after the deploy, apply `0185` by hand via `fly ssh console -a courtmastr-academy-api` and `backend.v2.migrations.run_pending_migrations`. It aborts without touching the existing index if any child already has two non-ended locked enrollments; production had zero `held` rows when this was written. Afterwards run the drift audit (`--dump` on Fly, `--check` locally) and expect `ok: true`. No env vars.

## Risk / rollback

Low. The script is read-only and not on any request path. The logging change adds one warning on an error path and alters no behaviour. The migration rebuilds one partial index under the same name; the application-level duplicate checks stay in force during the brief drop-and-create. To roll back, revert this PR's merge commit; if `0185` was already applied, the wider index is safe to leave in place.
