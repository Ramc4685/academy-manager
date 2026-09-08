# owner-admin-role-split

PR: #660

## What changed
First slice of the role model (design: PR #656). **Owner** is now the
academy's money-and-governance role; **admin** is operations.

- Owner-only (47 routes): refunds, discounts and credits, tuition-discount
  edits, undo-paid, invoice adjustments/void/refund, withdrawal-credit
  approval, pricing catalog writes, fee-policy and Stripe-connect changes,
  price overrides and enrollment fee waivers, all coach payout/payroll/pay-rate
  routes, revenue/economics/KPI/refund/deposit reports and CSV export, audit
  log. Non-owners get 404, like every persona guard.
- Admin keeps everything operational, including recording manual payments,
  seeing any family's balance, chasing dues, and expenses.
- Only owners can create, grant, revoke or replace the `admin`/`owner` roles
  (403 otherwise). Replacing a role also checks the roles the target holds,
  so an admin cannot demote an owner.
- Admin UI: Coach payouts, Reports (except Dues) and Audit logs leave the
  nav for non-owners; dashboard revenue tile and chart are owner-only;
  Refund/Discount/Undo/Adjustment actions and the Fees/Gateway/Roles settings
  panels show "Owner only" to admins; the sidebar pill reads Owner or Admin.

## Deploy notes
**Run migration `0165_grant_owner_to_existing_admins` by hand before, or
immediately after, deploying.** Boot migrations are off in prod
(`V2_RUN_MIGRATIONS_ON_BOOT=false`, #629), and until 0165 runs every existing
admin, including the owner, is admin-only and loses the money screens. The
migration adds `owner` to every membership that has `admin` and mirrors it
into `users.roles`; it is idempotent. No env vars. The `enable_owner_role`
flag is untouched and still only governs the franchise rollup.

Admins invited after this deploy are admin-only by default; grant `owner`
from the user's page when you mean it.

## Risk / rollback
Medium. If the migration is skipped, the owner is locked out of money
screens until it runs (data is untouched). Revert the PR to restore the old
single admin role; the extra `owner` role on memberships is harmless to the
old code, which already accepted it.
