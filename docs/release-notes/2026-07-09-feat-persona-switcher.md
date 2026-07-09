# feat-persona-switcher

Branch: `feat/persona-switcher`

## What changed
Users who hold more than one role (e.g. an admin who also coaches, or a
coach who is also a parent) can now switch which persona's view they're
in from a header dropdown, instead of being locked to whichever route
they navigated to directly.

- **Additive role management**: two new identity use cases,
  `AddUserRole`/`RemoveUserRole`, let an admin grant or revoke a single
  role without clobbering the user's other roles (the existing
  `ChangeUserRole`/role-PATCH endpoint replaces all roles and is
  unchanged, kept for backward compatibility). Every mutation updates
  both the legacy `users` doc and the SaaS source of truth
  `academy_memberships.roles`.
- **New admin endpoints**: `POST /api/v2/admin/users/{user_id}/roles`
  and `DELETE /api/v2/admin/users/{user_id}/roles/{role}`. Guarded so a
  user always keeps ≥1 role, and an admin cannot remove their own
  `admin` role (409 in both cases). Wrong-persona access returns 404,
  matching the existing convention.
- **Admin UI**: the user detail page's single-role `RoleChangePanel` is
  replaced by a `RolesPanel` — a checkbox per role plus a reason field,
  saved as a diff of add/remove calls.
- **`PersonaSwitcher` component**: mounted in the admin, coach, and
  parent header shells. Only renders for users holding 2+ roles; lists
  the personas the user holds and navigates to that persona's home
  route (`/admin`, `/coach/today`, `/parent/payments`) on selection.
  Single-role users see nothing new.

Coach and parent routes were not touched — they already authorize via
`claims.roles` and scope by `claims.user_id`, so an admin holding an
additional role gets read/write parity with any other user in that
role automatically (e.g. an admin added as `coach` shows up wherever
`GET /admin/users?role=coach` is used, such as the session coach
picker).

## Deploy notes
None required. No migration. New endpoints are additive; existing
single-role PATCH endpoint and `ChangeUserRole` flow are untouched.
Backend + frontend, both covered by the standard CI deploy pipeline.

## Verification
- Backend: `ruff format --check .`, `ruff check .`, and
  `pytest v2/tests -q` — 2140 passed, 13 pre-existing failures in
  `test_coach_skill_routes.py`/`test_parent_progress_routes.py`
  unrelated to this change (Python 3.14 `asyncio.get_event_loop()`
  incompatibility in unrelated test setup code, not touched here).
  The identity/admin-directory suites relevant to this feature
  (`test_admin_directory.py`, `application/identity/`) pass cleanly
  (32/32).
- Frontend: `npm run typecheck` and `npm run lint` clean (only
  pre-existing warnings in unrelated files).
- Manual smoke: add a second role to an admin user via the Roles
  panel, confirm the persona switcher appears and navigates correctly
  between persona homes, confirm self-admin-role removal and
  last-role removal are both rejected with an inline 409 error.

## Risk / rollback
Low — additive only. No existing route's behavior changes; a
single-role user's experience is identical to before (no switcher,
existing role-change endpoint intact). Revert the merge commit if
issues surface; no irreversible state beyond the role list mutations
this feature itself makes, which are simple set additions/removals
recorded in the existing audit log.
