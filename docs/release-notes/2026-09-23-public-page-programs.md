# Public tenant page B1: Program entity, per-class publish switch, public page settings, migration 0194

PR: #934

## What changed

- New tenant-scoped **Program** entity in the Enrollment context (`contexts/enrollment/domain/programs.py`): name, public description, level label, age band (`min_age`/`max_age`, max open-ended for adults), sort order, archived flag, timestamps. Stored in a new `programs` collection through `MongoProgramRepository`.
- Per-class public fields on the existing `sessions` rows: `program_id`, `published`, `price_period` (`month` / `class` / `term`; unset means the academy default), `coach_display` (`full_name` default, `first_name`, `hidden`), `public_description`, `level`, `age_band`. They are written only by targeted `$set`/`$unset` in `MongoClassPublicProfileRepository`, never through a `Session` round-trip, so an ordinary class edit cannot reset them. A missing `published` key reads as private: every existing class stays off the public page until an admin switches it on.
- Academy-level `public_page` settings subdocument (`contexts/identity/domain/public_page.py`): `published` false, `show_price` true, `show_availability` true, `price_period_default` "month", `trials_open` true, `privacy_notice_url` null. Defaults are merged on read, so the existing academy needs no backfill; updates write only the keys sent (dotted `$set`). Use cases `GetPublicPageSettings` / `UpdatePublicPageSettings`; the admin endpoint for them is B5's.
- Admin use cases `CreateProgram`, `UpdateProgram`, `ArchiveProgram`, `ListPrograms`, `AssignClassToProgram`, `SetClassPublicFields`, `ListClassPublicProfiles`, wired in the new `composition/public_page_admin.py` (nothing added to `composition/admin.py`) at `app.state.admin_public_page`.
- Admin endpoints, all `require_persona("admin")`: `GET/POST /api/v2/admin/programs`, `PATCH /api/v2/admin/programs/{program_id}`, `POST /api/v2/admin/programs/{program_id}/archive`, `GET /api/v2/admin/class-public-profiles`, `PUT /api/v2/admin/sessions/{session_id}/program`, `PATCH /api/v2/admin/sessions/{session_id}/public-fields`. Another academy's program or class is a 404; the tenant never comes from the body.
- `programs` added to `TENANT_OWNED_COLLECTIONS`. New unit, interface and real-mongod contract tests.
- Design brief and prototype for the public page added under `docs/design/public-tenant-page/`.
- Backend only: no frontend change and no public (anonymous) route yet.

## Deploy notes

- Migration **0194_programs** is applied by the production migrate job (dry run, then the Fly release command) per `docs/runbooks/migrations-rollout.md`; expect `0194_programs` in the dry run's pending list. It creates `programs_academy_program_unique` and `programs_academy_sort` on the new, empty `programs` collection and a non-unique, non-partial `sessions_academy_published` on `sessions`. Index builds only, no document is modified. Never hand-apply it.
- No feature flag, no environment variable, no backfill.

## Risk / rollback

- Low: new collection, new routes, and new optional keys on `sessions` that no existing read path looks at. Nothing is public until B2 ships and an admin publishes a class and the page.
- Rollback: revert the PR. If 0194 was applied, the indexes and any stored public fields are harmless and can stay; to remove them: `db.programs.drop()`, `db.sessions.dropIndex("sessions_academy_published")` and `db.v2_migrations.deleteOne({version: "0194_programs"})`.
