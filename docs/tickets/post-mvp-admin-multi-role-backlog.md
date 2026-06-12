# Post-MVP Admin Multi-Role Users — Backlog

Tickets to make one user account support multiple academy roles, especially
parent + coach, without manual database updates or duplicate emails.

> Status: backlog (not started). Refine each ticket against
> `docs/plans/2026-06-10-admin-multi-role-users.md` before implementation.

---

## AMR-01 — Backend multi-role identity update use case

- **Type:** Backend / Identity
- **Estimate:** 5h
- **GitHub:** [#161](https://github.com/Ramc4685/academy-manager/issues/161)
- **Problem:** The current admin role update replaces `roles` with a single value, so a parent cannot also become a coach without losing parent access.
- **Scope:** Add `ChangeUserRoles`, repository `change_roles`, role normalization, audit logging, and synchronization between `users.roles`, legacy `users.role`, and `academy_memberships.roles`.
- **Acceptance:**
  - [ ] User can be updated to `roles=["parent", "coach"]`.
  - [ ] Legacy `role` derives to `coach` for parent+coach.
  - [ ] `academy_memberships.roles` is updated.
  - [ ] Empty roles are rejected.
  - [ ] Removing `parent` is blocked when linked students exist.
  - [ ] Removing `coach` is blocked when active sessions exist.
  - [ ] Focused backend application tests pass.

## AMR-02 — Admin BFF route for multi-role updates

- **Type:** Backend / Interface
- **Estimate:** 3h
- **GitHub:** [#162](https://github.com/Ramc4685/academy-manager/issues/162)
- **Problem:** Admin clients only have a single-role endpoint.
- **Scope:** Add `PATCH /api/v2/admin/users/{user_id}/roles` with `{ roles, reason }`, wire dependencies/composition, and preserve existing `/role` endpoint for compatibility.
- **Acceptance:**
  - [ ] Admin can patch multiple roles.
  - [ ] Non-admin personas receive 404 on the route.
  - [ ] Admin cannot remove their own `admin` role.
  - [ ] Response includes full role list.
  - [ ] Focused interface tests pass.

## AMR-03 — Admin UI multi-role editor

- **Type:** Frontend / Admin UI
- **Estimate:** 6h
- **GitHub:** [#163](https://github.com/Ramc4685/academy-manager/issues/163)
- **Problem:** Admin UI exposes users as one role, forcing manual Mongo changes for parent+coach users.
- **Scope:** Add role checkboxes/toggles for existing users, update API client types, display multiple role chips, and refresh user lists after save.
- **Acceptance:**
  - [ ] Admin can select both Parent and Coach for one user.
  - [ ] At least one role must remain selected.
  - [ ] Role chips show all assigned roles.
  - [ ] Coach and parent filters continue to include multi-role users.
  - [ ] `pnpm typecheck` passes.

## AMR-04 — Persona switcher for multi-role users

- **Type:** Frontend / Auth UX
- **Estimate:** 4h
- **GitHub:** [#164](https://github.com/Ramc4685/academy-manager/issues/164)
- **Problem:** Multi-role users currently land on one role by priority and have no clear way to switch surfaces.
- **Scope:** Add a small authenticated persona switcher to admin, coach, and parent layouts for users with more than one role.
- **Acceptance:**
  - [ ] Parent+coach users still land on coach by default.
  - [ ] Parent+coach users can navigate to parent and coach homes.
  - [ ] Single-role users do not see a switcher.
  - [ ] UI fits mobile coach/parent layouts.
  - [ ] `pnpm typecheck` and `pnpm lint` pass.

## AMR-05 — Multi-role data consistency runbook and repair script

- **Type:** Ops / Data repair
- **Estimate:** 4h
- **GitHub:** [#165](https://github.com/Ramc4685/academy-manager/issues/165)
- **Problem:** Existing users may have mismatched `users.roles`, `users.role`, session coach assignments, and `academy_memberships.roles`.
- **Scope:** Add a dry-run-first script and operator runbook for targeted role repair and membership synchronization.
- **Acceptance:**
  - [ ] Script defaults to dry-run.
  - [ ] Script can target one email and academy.
  - [ ] Production apply requires explicit confirmation.
  - [ ] Runbook explains current auth behavior and emergency repair steps.
  - [ ] Script `--help` exits 0.

## AMR-06 — End-to-end verification for parent+coach account

- **Type:** Test / E2E
- **Estimate:** 4h
- **GitHub:** [#166](https://github.com/Ramc4685/academy-manager/issues/166)
- **Problem:** Multi-role behavior spans backend auth, admin role editing, post-login redirects, coach routes, and parent routes.
- **Scope:** Add or update E2E coverage for a parent+coach user and record focused verification.
- **Acceptance:**
  - [ ] `/me` returns both `parent` and `coach`.
  - [ ] Post-login redirects to coach home.
  - [ ] Parent route is accessible.
  - [ ] Coach route is accessible.
  - [ ] Coach session selector includes the user.
  - [ ] Pre-push checks pass or skipped checks are documented.
