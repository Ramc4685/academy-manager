# fix-uim4-archived-session-types

PR: #TBD

## What changed
Archiving a session type is no longer a one-way door. Admins can tick "Show
archived" on `/admin/settings?panel=session-types` to see soft-deleted pricing
plans (greyed, badged ARCHIVED) and reactivate any of them from its row.
`GET /admin/session-types` takes a new `include_archived` query param — off by
default, so every existing caller keeps seeing active types only.

## Deploy notes
None. No migration, no env var, no manual step: archived rows already exist in
the `session_types` collection with `is_active: false`, and this only adds a
read path that stops filtering them out.

## Risk / rollback
Low. The new `include_archived` param defaults to false, so the parent and
coach billing paths — which resolve prices through `list_active()` — are
untouched; a bug here would at worst show or hide rows in one admin settings
tab. Reactivation is the existing `PATCH {is_active: true}` route, already used
by the edit dialog. Roll back by reverting the commit; nothing persists that
the previous code cannot read.
