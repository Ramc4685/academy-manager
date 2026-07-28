# fix-uim11-franchise-rollup

PR: #PENDING

## What changed
Added the first genuinely multi-academy surface: a franchise owner can now see
consolidated revenue and outstanding dues across every academy they own,
instead of logging into each one and summing by hand.

Backend — `owner` is now a value of the academy-scoped `Role` literal
(`backend/v2/contexts/identity/domain/models.py`), so it can be granted on an
`AcademyMembership` through the existing admin role endpoints. A new
`GetOwnerFinancialRollup` use case
(`backend/v2/contexts/billing/application/use_cases/owner_rollup.py`) resolves
the rollup's academy set **server-side from the caller's own active `owner`
memberships** and then reads each academy through
`MongoAcademyFinancialSnapshotReader`, whose every query carries an explicit
`academy_id` filter. The new route is `GET /api/v2/owner/rollup`
(`backend/v2/interfaces/owner/`), mounted only when `enable_owner_role` is on.

Frontend — new `(owner)` route group with `/owner`, a totals strip plus a
per-academy table whose rows deep-link into that academy's admin dashboard
(switching the active academy on the way). The entry point is an "All
academies" item in the existing `TenantSwitcher`, shown only when the user
holds more than one `owner` membership. `UserRole` gained `owner`, and the
persona switcher was narrowed to a new `PersonaRole` type since `owner` is a
scope rather than a persona shell.

## Deploy notes
No migrations and no new env vars. The feature ships dark: `enable_owner_role`
defaults to `False`, which leaves both the composition root and the router
unmounted, so `/api/v2/owner/*` 404s. To enable, set `ENABLE_OWNER_ROLE=true`
and grant an `owner` role on the relevant academy memberships. Verify in
staging against two seeded academies before enabling in production.

## Risk / rollback
The cross-academy read is the risk, and it is contained two ways: the academy
set comes only from the caller's own active `owner` memberships — the request
tenant header can neither add nor remove an academy — and no cross-tenant
Mongo query is ever issued, since the reader iterates that membership-derived
list running one ordinary `academy_id`-filtered read per academy. Both
properties are asserted directly
(`backend/v2/tests/interface/test_owner_rollup_routes.py` parametrises the
tenant header across an academy the caller does *not* own;
`backend/v2/tests/unit/test_owner_rollup_snapshot_reader.py` asserts every
emitted query filter). A caller with no owner membership, a suspended owner
membership, or the flag off all get 404 rather than 403, so route existence
is not leaked. Rollback: set `ENABLE_OWNER_ROLE=false` (instant kill switch),
then revert this PR if needed — the feature is read-only, so nothing to undo
in data.

Verified: full backend `v2/tests` suite green, `ruff check v2` clean,
`lint-imports` 5/5 contracts kept, mypy baseline gate clean (0 new errors);
frontend `pnpm typecheck` and `pnpm lint` clean (0 errors), full `pnpm e2e`
suite green.
