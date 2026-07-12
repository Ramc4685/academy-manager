# feat-multi-persona-view-switcher-additive-role-management

PR: #297

## What changed
One user can now hold multiple personas (admin/coach/parent) and switch between their views.

- **Backend:** additive `AddUserRole`/`RemoveUserRole` use cases; `MongoUserRepository.add_role/remove_role` write BOTH the legacy `users` doc and `academy_memberships` (source of truth for auth claims; membership row upserted on add). New endpoints `POST /admin/users/{id}/roles` and `DELETE /admin/users/{id}/roles/{role}` with guards: 409 on removing your own admin role or a user's last role; wrong persona still 404s.
- **Frontend:** `PersonaSwitcher` header dropdown (shown only for users with ≥2 roles; lists exactly the personas they hold — covers admin↔coach, coach↔parent, any combination) mounted in the admin, coach, and parent shells. Admin user-detail `RolesPanel` and the Settings roles panel both use additive role management (the old single-role PATCH silently clobbered `roles`).

Spec: `docs/superpowers/specs/2026-07-09-admin-coach-toggle-and-parent-invite-design.md` (Enhancement 1)
Plan: `docs/superpowers/plans/2026-07-09-persona-switcher-additive-roles.md`
Release note: `docs/release-notes/2026-07-09-feat-persona-switcher.md`

## Deploy notes
No migration detected in the diff. Confirm no manual env var or manual step is needed before merge.

## Risk / rollback
_Auto-generated stub — author: fill in what breaks if this is wrong and how
to roll back before merge._ Revert the merge commit if this regresses.
