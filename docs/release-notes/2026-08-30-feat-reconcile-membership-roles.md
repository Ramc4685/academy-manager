# reconcile-membership-roles

PR: #560

## What changed
New operational script `backend/v2/scripts/reconcile_membership_roles.py`
(issue #508). PR #502 made role demotions mirror into `academy_memberships` —
the collection SaaS claims are built from — but shipped no backfill, so every
demotion applied before it left the membership row still serving the old,
higher role: live admin claims for staff the directory says are parents. The
script compares each `users` doc's roles against its alias-resolved membership
rows (the same alias set and foreign-ownership check the write path uses) and
reports every row whose privilege ceiling exceeds the directory's, inactive
and terminated accounts first. With `--fix` it rewrites those rows by their
own `_id` to the directory's role list, raising `RoleRevocationFailed` on a
lost write. Alias collisions fail closed — the account is reported for a
human, never half-corrected — and rows with an empty directory role list or
no resolvable directory doc (orphans) are surfaced but not auto-revoked.

## Deploy notes
No migration and no runtime behavior change; the script only runs when
invoked. After deploy, run
`python -m backend.v2.scripts.reconcile_membership_roles` against production
to get the report, review it, then re-run with `--fix` to correct the stale
rows. Any account it lists under COLLISION or ORPHAN needs manual review —
the script deliberately refuses to touch those.

## Risk / rollback
Without `--fix` the script writes nothing. With it, every write narrows a
membership's roles down to what the `users` directory already claims — it can
reduce effective access, never widen it. The main operational risk is
over-narrowing an account whose directory doc is itself wrong; the dry-run
report exists so that is reviewed before anything is written. Rollback is
simply not running the script; a mistaken correction is repaired by
re-granting the role through the admin UI, which dual-writes both stores
since #502.
