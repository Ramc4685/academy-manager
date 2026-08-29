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
