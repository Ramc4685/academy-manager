# UIM2 — GET /me/memberships + real TenantSwitcher
Status: TODO
Size: S · Depends on: none · Tracker: ../TRACKER.md

## User value
The TenantSwitcher (`frontend/components/admin/tenant-switcher.tsx`) currently renders from a single-academy stub, so multi-academy users (franchise owners, platform staff with tenant memberships) can never switch tenants. This route is also a hard dependency of UIM11 (franchise rollup).

## Backend status (verified — routes, DTO fields)
- `GET /me` exists (`backend/v2/interfaces/me_routes.py`) → `MeResponse {user_id, email, academy_id, roles, membership_id, platform_roles}`. No memberships route yet.
- Repo method **exists**: `MongoMembershipRepo.list_memberships_for_user(user_id)` at `backend/v2/contexts/identity/infrastructure/mongo_membership_repo.py:94` — returns ALL membership rows (including invited/suspended/removed; caller must filter `.is_active()`).
- `AcademyMembership` rows carry `membership_id, academy_id, user_id, roles, status, invited_by/at, accepted_at` — note **no academy display name**; the route must join academy display names (academy/tenant record by `academy_id`) or return `academy_name` best-effort (frontend already has `deriveAcademyLabel` fallback).
- Auth: `get_auth_claims` (LoadAuthClaims path) resolves the active academy; the new route uses `claims.user_id` and marks the entry matching `claims.academy_id` as active.

## Frontend to build (pages/components/queries — concrete)
- `frontend/lib/api/v2/memberships.ts:41-61` — replace the stub in `listMyMemberships()` with `return apiFetch<MyMembershipsResponse>("/me/memberships")` (per the file's own TODO(wave5-A) at lines 37-46). Keep `MyMembershipsResponse {memberships: AcademyMembershipSummary[], active_academy_id}` and `AcademyMembershipSummary {academy_id, academy_name, academy_slug, roles, status, is_default}` — shape the backend view model to match so `TenantContext` and the switcher need zero changes. Keep `deriveAcademyLabel` as fallback when `academy_name` is null.
- No new query keys needed if `TenantContext` already fetches via `listMyMemberships`; if a key is added, put it under a `me` namespace in `frontend/lib/query/keys.ts`.

## Backend to build (if any — route, use case, tests, manifest registration)
- New `GET /me/memberships` in `backend/v2/interfaces/me_routes.py` (same router, tags=["auth"], any authenticated persona — it is the caller's own data, no persona gate beyond `get_auth_claims`):
  - View models: `MembershipSummaryView {academy_id, academy_name: str | None, academy_slug: str | None, roles, status, is_default: bool}` and `MyMembershipsResponse {memberships, active_academy_id}`.
  - Wire via app.state (BFF must not import infrastructure directly — follow the existing composition pattern; expose a small `list_my_memberships` use case in the identity application layer that calls `list_memberships_for_user`, filters to active, and joins academy names).
  - `is_default`/active = row whose `academy_id == claims.academy_id`.
- Interface test: authenticated user with 1 and with 2 memberships; unauthenticated 401; response shape matches frontend types.
- Manifest: **no frontend route added**, so `docs/qa/...inventory-manifest.json` needs no new entry; `backend/v2/tests/unit/test_audit_inventory_manifest.py` unaffected.

## Implementation steps (phased if L; each phase one PR)
1. Identity application use case + view models + `GET /me/memberships` route + interface tests.
2. Frontend: swap the stub call in `memberships.ts`, delete the "avoid speculative 404" comment block.
3. Verify TenantSwitcher UX: 1 membership → unchanged pill (component branch at `tenant-switcher.tsx:86` `single = memberships.length === 1`); seed a second membership locally → dropdown/switcher goes live (`memberships.map` at :121).

## Files to change/create
- Modify: `backend/v2/interfaces/me_routes.py`, identity application layer (new `list_my_memberships` use case file), composition root wiring, `frontend/lib/api/v2/memberships.ts`
- Create: interface test (e.g. `backend/v2/tests/interfaces/test_me_memberships.py`)

## Verification
- `pytest` new interface tests; `pnpm typecheck`
- e2e/manual: single-membership user sees identical switcher; multi-membership user can switch; zero console 404s (the stub existed precisely to keep zero-console-error e2e assertions green — the real route removes the need)

## Risks / rollback
- Inactive memberships must be filtered server-side or the switcher will offer suspended tenants.
- Academy-name join adds a read per membership — bound is tiny (users have few memberships).
- Rollback: revert frontend to the stub; the route is additive.

## PR checklist (release note · TRACKER.md · plan Status → DONE)
- [ ] Release note
- [ ] Update TRACKER.md row UIM2
- [ ] Plan Status → DONE
