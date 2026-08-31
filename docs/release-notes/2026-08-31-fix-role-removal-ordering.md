# role-removal-ordering

PR: #597

## What changed
`DELETE /admin/users/{id}/roles/{role}` wrote the `users` directory before it
mirrored the change into `academy_memberships`. `_pull_membership_role` can
raise — an alias-matched row owned by another account, or a revocation write
that did not land — and nothing rolled the directory write back, so the audit
insert never ran either. The directory said `parent` while the membership still
said `admin`, and since `require_persona` reads `claims.roles`, which IS
`membership.roles`, the demoted account kept live admin access while the admin
UI showed it demoted. A retry re-raised at the same point forever and the
reconcile script withholds correction for the alias-collision class, so there
was no API-reachable remedy.

Role removal now revokes the membership FIRST and writes the directory second,
the same direction-aware ordering `change_role` already had, so a partial
failure can only leave effective access at what the actor asked for or
narrower. The additive path keeps its directory-first order.

Also closes a vacuous guard: neutering the removal path's `matched_count` check
left all 24 tests green. The removal path now has the twin of the replacement
path's lost-write test, plus the two assertions the alias-owned removal test
omitted (directory roles unchanged, audit_logs count == 0).

## Deploy notes
None. No migration, no new environment configuration, no schema change. Any
account already corrupted by this bug — directory demoted, membership still
holding the old role — is NOT repaired by this deploy; it stops new ones. Those
accounts still read as privileged in claims and need a manual membership fix,
and `reconcile_membership_roles.py` will not correct the alias-collision class
on its own. A post-deploy audit for `academy_memberships` rows whose `roles`
exceed the matching `users.roles` would surface them.

## Risk / rollback
Low. Two statements move within one function; no call signature, route, or
schema changes, and the additive path is byte-for-byte unchanged. One
behaviour delta from main, in the fail-closed direction: if the `users` doc is
deleted between the read and the update, the membership grant is now revoked
before the call returns None, so access ends up narrower rather than wider.
Issue #591's second, lower-severity race (two admins removing two different
roles concurrently, membership can end at `roles: []`) is deliberately NOT
addressed and is left exactly as on main. Rollback is a straight revert; no
data migration to unwind.
