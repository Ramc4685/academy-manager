# UIM11 — Franchise cross-academy rollup
Status: TODO
Size: L · Depends on: UIM2 (GET /me/memberships), `enable_owner_role` flag · Tracker: ../TRACKER.md

## User value
An owner operating multiple academies (franchise) currently has to log into each academy separately and mentally sum the numbers. A consolidated rollup — per-academy revenue, outstanding dues, and totals — is the first genuinely multi-academy feature and the thing a franchise buyer will ask for on day one. (Deferred from the Payment Visibility initiative's Phase 3.)

## Backend status (verified)
- **Nothing exists.** `grep -ri franchise backend/v2 frontend/lib` returns zero hits.
- `enable_owner_role: bool = Field(default=False)` exists but is inert — `backend/v2/shared/config/settings.py:58`.
- Identity building blocks exist: `AcademyMembership` (`backend/v2/contexts/identity/domain/models.py:98`, unique `(academy_id, user_id)`, per-academy roles) and repo method `list_memberships_for_user` (per audit item #2 / UIM2). `Role = Literal["admin","coach","parent"]` (`models.py:35`) — **"owner" is not a role value yet**; adding it is part of this work.
- Per-academy financial reads exist tenant-scoped (owner dashboard PR #295, `GET /admin/finance/revenue` at `billing_routes.py:705`, dues queries) but every one resolves a single tenant.

## The authorization model (design this carefully — deliberately CROSS-tenant)
This feature must NOT trust the tenant header. The rollup's academy set is resolved **server-side from memberships**:
1. Authenticate the user (normal claims).
2. Load `list_memberships_for_user(user_id)`; filter to memberships where the membership carries the `owner` role and status is active.
3. The rollup aggregates **exactly that academy set** — the request's tenant header contributes nothing to scoping and must not widen it. An owner of academies A and B sees A+B regardless of which tenant they're "in"; a user with zero owner memberships gets 404 (persona-shaped convention).
4. Everything stays flagged behind `enable_owner_role`; flag off → routes 404.

This is an explicit, narrow exception to "all reads are tenant-scoped": the aggregation layer iterates the membership-derived academy list and runs the existing tenant-scoped queries once per academy, rather than issuing any cross-tenant Mongo query. That keeps `TenantScopedRepository` invariants intact.

## Backend to build (Phase 1 — one PR)
New owner-scoped read surface. Recommended shape: new interface package `backend/v2/interfaces/owner/` (persona-shaped BFF like admin/coach/parent) backed by a read model in the billing/finance context:
- `Role` literal gains `"owner"`; membership writes (manage_user_roles) allow granting it; `require_persona("owner")` support in `backend/v2/shared/http` (claims must expose owner memberships, not a single-tenant role).
- Use case `GetOwnerFinancialRollup` in `backend/v2/contexts/billing/application/use_cases/owner_rollup.py`: input user_id; resolves owner academies via an identity-facing Protocol port (`application/ports.py`), then per academy invokes existing revenue/outstanding queries (reuse `revenue_query`, dues/outstanding read models) and returns `{ academies: [{ academy_id, name, revenue_by_month, outstanding_cents, ... }], totals: {...} }`.
- Route `GET /owner/rollup?period=...` in `interfaces/owner/rollup_routes.py`; registered in the audit inventory manifest (`backend/v2/tests/unit/test_audit_inventory_manifest.py`); gated on `enable_owner_role` (404 when off) and wrong-persona 404.
- Tests: unit tests for membership-derived scoping (user with 0/1/2 owner memberships; non-owner membership excluded; tenant header ignored), flag-off 404, manifest registration.

## Frontend to build (Phase 2 — one PR)
- New route group `frontend/app/(owner)/owner/dashboard` (or an "All academies" view reachable from the TenantSwitcher UIM2 builds — the switcher already learns the user's academies, so an "All academies" entry is the natural entry point).
- Page: totals strip (revenue, outstanding), per-academy table with drill-down links into each academy's admin dashboard (which switches tenant via the normal switcher mechanics), period picker.
- Data layer: `apiFetch` client + TanStack Query v5, keys under a new `owner` namespace in `frontend/lib/query/keys.ts`.
- Role gating in the frontend layout mirroring the flag (hide entry point unless memberships include owner).

## Implementation steps (phased; each phase one PR)
1. **Phase 0 (small, can ride with Phase 1):** add `owner` to the `Role` literal + membership grant path + claims plumbing, behind `enable_owner_role`.
2. **Phase 1 (backend):** ports + `GetOwnerFinancialRollup` + `interfaces/owner/` route + composition wiring + manifest registration + tests above.
3. **Phase 2 (frontend):** owner dashboard page + client + keys + entry point from TenantSwitcher.

## Flag rollout plan
- Ship all PRs with `enable_owner_role=False` (default). Enable in staging, grant an owner membership to a test user across two seeded academies, verify rollup math against per-academy dashboards. Enable in prod only for the first real franchise account; the flag stays the kill switch.

## Files to change/create
- `backend/v2/contexts/identity/domain/models.py` (Role literal), `manage_user_roles.py`, claims loader.
- `backend/v2/contexts/billing/application/ports.py`, `application/use_cases/owner_rollup.py`, infrastructure adapter for the membership port.
- `backend/v2/interfaces/owner/{__init__,router,rollup_routes,deps}.py`; app router registration; `backend/v2/tests/unit/test_audit_inventory_manifest.py`.
- `frontend/app/(owner)/owner/dashboard/page.tsx` + layout; `frontend/lib/api/v2/owner.ts`; `frontend/lib/query/keys.ts`.

## Verification
- Unit: scoping tests listed above are the heart of it — assert the academy set comes only from owner memberships and the tenant header cannot add academies.
- Integration: two seeded academies, one owner user; rollup totals equal the sum of per-academy admin figures.
- Manifest test green; import-linter (DDD layering) green; wrong-persona and flag-off 404s.

## Risks / rollback
- **Cross-tenant read is the risk.** Mitigate by never issuing a cross-tenant query — iterate membership academies through existing tenant-scoped repos — and by the scoping unit tests. Get boundary-reviewer eyes on Phase 1.
- Rollback: flag off (instant), then revert PRs. No data migration involved (read-only feature; the only write-side change is the role grant path).

## PR checklist (per phase)
- [ ] Release note line
- [ ] TRACKER.md row updated (Status, PR/Issue)
- [ ] This plan's Status → DONE (PR #NNN, date) after Phase 2
