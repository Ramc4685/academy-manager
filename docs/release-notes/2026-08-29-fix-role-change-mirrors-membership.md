# role-change-mirrors-membership

PR: #502

## What changed
`change_role` (the admin role-replace endpoint) wrote only the legacy `users`
doc and an audit row, never `academy_memberships` — which is where
`LoadAuthClaims` builds SaaS claims from. A demotion therefore showed as
`parent` in the directory, the audit log and the admin UI while the account
kept live `admin` claims. The replacement is now mirrored into this academy's
membership row, resolved through the same alias set the read path uses and
written by row `_id` so an alias collision cannot flatten another account's
roles. A narrowing that cannot claim every alias-visible row now fails closed
instead of reporting a demotion that never took effect, and the two writes are
ordered by privilege: demotions revoke the membership first, promotions write
the directory first.

`remove_role` gets the same treatment, and it is the half that matters in
production: `change_role` has no frontend caller, so every demotion the admin
UI can actually perform goes through `DELETE /admin/users/{id}/roles/{role}`.
That path mirrored membership with a single `update_one` keyed on the exact
resolved `user_id` — for an alias-keyed row it `$pull`ed nothing while the
directory, the audit row and the UI all reported the role removed. Removal now
resolves through the same alias set, skips rows owned by another account
(failing closed, since a removal always drops a role), writes by row `_id`,
and checks `matched_count`. The additive path keeps its exact-id upsert:
granting through a row auth cannot reach is inert, and the upsert is what
creates the row for legacy accounts that have none.

## Deploy notes
No migration. Accounts demoted BEFORE this ships may still hold a stale
`academy_memberships.roles` granting the old role — those rows are not
retro-corrected here, so re-apply any demotion made prior to this deploy to be
certain it took effect.

## Risk / rollback
`RoleRevocationFailed` maps to 502, so a genuine identity collision now
surfaces as a failed role change rather than a silent partial one. That is the
intent — a collision needs a human — but it is a new user-visible failure on
the admin path, and how the admin UI renders it has not been verified. The
privilege table (`owner > admin > coach > parent/student`) decides write order
only; it grants nothing on its own, so a wrong entry can misorder two writes
but cannot widen access. Roll back by reverting the merge commit — claims then
revert to being built from membership rows that the replacement path no longer
updates, i.e. back to the bug.
