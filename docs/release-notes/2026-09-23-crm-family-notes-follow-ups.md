# People CRM Phase 4a: family notes and follow-ups, migration 0195

PR: #947

## What changed

- Staff can write team notes on a family record (plain text, up to 4,000 characters) and edit or delete them; only the note's author or the academy owner may change one, and delete is a soft delete. Coach notes stay read-only in the child drawer.
- Staff can add dated follow-ups to a family, assign each to an admin or owner of the academy, and mark them done or reopen them. Both live on a new **Notes & follow-ups** tab on `/admin/families/[parentId]`.
- The admin dashboard gains a **My follow-ups** card: the signed-in staff member's open follow-ups that are overdue or due today, linking to each family.
- New admin endpoints, all `require_persona("admin")` (coaches and parents get the usual 404): `GET/POST /api/v2/admin/families/{parent_id}/notes`, `PATCH/DELETE .../notes/{note_id}`, `GET/POST /api/v2/admin/families/{parent_id}/follow-ups`, `PATCH .../follow-ups/{follow_up_id}`, `GET /api/v2/admin/follow-ups?assignee=me|all&bucket=overdue|today|upcoming|done`. Another academy's family is a 404; no request body carries an academy.
- No change to the family Billing tab, `main.py` or `composition/admin.py`.

## Deploy notes

- Migration **0195_crm_family_notes_follow_ups** is applied by the production migrate job (dry run, then the Fly release command) per `docs/runbooks/migrations-rollout.md`; expect it in the dry run's pending list (after 0192-0194 if those have not shipped yet). It only creates six indexes on two new, empty collections (`family_notes`, `family_follow_ups`); every index leads with `academy_id`, two are unique, none is partial. No document is modified. Never hand-apply it.
- No feature flag, no environment variable, no backfill.

## Risk / rollback

- New collections and routes only; nothing existing reads them. If the tab or card misbehaves, revert the PR: the routes and UI disappear and the two collections (and their indexes) can stay in place harmlessly.
- The family check reuses the family index (cached for a minute, re-checked once against a fresh build on a miss), so a note on a brand-new family costs one extra index build.
