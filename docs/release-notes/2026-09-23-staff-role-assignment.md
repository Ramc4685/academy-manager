# Staff page: owners assign billing and front desk roles, and the last owner is protected (L2c, #553)

PR: #960

## What changed

- On the Staff page (`/admin/users/{id}`), owners can now give or remove the **Billing** and **Front desk** staff roles, alongside owner, admin, coach, assistant coach and parent. Each role shows a one-line hint saying what it can do. Owners also see the two roles in the Add-user role picker.
- Admins who are not owners still see only the operations roles (parent, coach, assistant coach). If an account holds a staff role that the admin cannot change, the page lists it under "Also holds". On the server, granting or revoking billing, front desk, admin or owner was already owner-only (L2a, #957).
- Every academy always keeps at least one live owner. The server refuses with 409 when a change would remove the owner role from the last active owner, replace all of that owner's roles, or disable that owner's account. Invited or suspended owners do not count toward the total.
- Every role grant and removal writes a `user.role_added` or `user.role_removed` audit row. This is unchanged.

## Deploy notes

- No migration, no feature flag, no environment variable and no backfill.
- Owner steps: none. After the deploy, an owner can open a staff member's page and assign Billing or Front desk.

## Risk / rollback

- The last-owner guard adds one indexed count of active owner memberships, and only when a change touches an owner. A request that would have left an academy with no owner now gets a 409 instead of succeeding.
- To roll back, revert the PR. The role form goes back to its previous options and the guard is removed. Roles assigned in the meantime stay valid, because the L2a backend already understands them.
