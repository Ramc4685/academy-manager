# Owner / Admin Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce an academy-level **owner** role that alone may perform money-governance actions, and make **admin** an operations role, without changing anything an existing admin can do today (every existing admin membership is granted owner by migration).

**Architecture:** Reuse the existing `owner` role literal (already in both `Role` unions and ranked above admin in `_ROLE_PRIVILEGE`). Add a `require_owner()` FastAPI guard next to `require_persona` (404 on miss, like every persona guard) and apply it to the money-governance routes listed below. Role grants stay on admin routes but gain an action-level rule: granting or revoking `admin`/`owner` requires the caller to hold `owner` (403). Frontend derives `isOwner` from `CurrentUser.roles`, hides owner-only nav items, dashboard revenue, and money actions for non-owners, and shows an "Owner only" panel on owner-only routes. Migration 0165 grants `owner` to every existing admin membership so nobody loses access on deploy; the split applies to admins invited from now on.

**Tech Stack:** FastAPI + Motor (backend/v2), Next.js 15 app router (frontend), Vitest (node env) and Playwright, pytest with xdist.

**Spec:** `docs/superpowers/specs/2026-09-04-role-model-and-screens-design.md` (on PR #656). Decisions: admin CAN record manual payments and see balances; admin CANNOT grant admin/owner; refunds/credits/pricing/payouts/reports/audit are owner-only.

## Global Constraints

- Work only in `/Users/ramc/Documents/Code/academy-manager/.worktrees/owner-split` (branch `feat/owner-admin-split`). Backend venv is symlinked at `backend/.venv`; frontend deps installed.
- Guards return **404** for a missing role (never 403) except the action-level role-grant rule inside an already-authorized admin route, which returns **403** with a clear message.
- `Role` is duplicated by hand in `backend/v2/shared/auth/claims.py:40` and `backend/v2/contexts/identity/domain/models.py:46`; do NOT add a new role name. Update the `owner` docstring in `models.py:42-45` to: academy-level owner (money + governance); a user holding owner in several academies also gets the franchise rollup.
- `enable_owner_role` (settings.py:69) stays as the franchise-rollup flag only. Remove the flag check that 404s owner grants in `directory_routes.py:191`.
- `backend/v2/composition/admin.py` is at its 4800-line cap: do not add lines there.
- New frontend routes: none. Existing route counts/QA manifest unchanged.
- Git hooks block `--amend`/rebase; make new commits. Do not push; the orchestrator pushes.
- Commit trailer: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1 (backend): `require_owner` guard and the owner-only route set

**Files:**
- Modify: `backend/v2/shared/http/persona.py` (add guard after `require_persona`)
- Modify: `backend/v2/contexts/identity/domain/models.py:42-46` (docstring)
- Modify: route modules under `backend/v2/interfaces/admin/` listed below
- Create: `backend/v2/tests/structural/test_owner_gate_policy.py`
- Modify: `backend/v2/tests/interface/conftest.py` (`_admin_claims`, `_claims`, `_make_admin_app`)
- Create: `backend/v2/tests/interface/test_owner_admin_split.py`

**Interfaces:**
- Produces: `require_owner() -> Callable[..., AuthClaims]` in `backend/v2/shared/http/persona.py`; `OWNER_ONLY_ROUTE_PATHS` frozenset in `backend/v2/interfaces/admin/owner_gate.py` (single source of truth used by the structural test).

- [ ] **Step 1: Guard.** In `persona.py` add:

```python
def require_owner() -> Callable[..., AuthClaims]:
    """Academy owner gate for money-governance routes (refunds, pricing,
    payouts, reports, audit, role grants). Misses are 404, like every persona
    guard, so the route's existence is never leaked."""

    async def _dep(claims: AuthClaims = Depends(get_auth_claims)) -> AuthClaims:
        if "owner" not in claims.roles:
            raise HTTPException(status_code=404, detail="Not found")
        return claims

    return _dep
```

- [ ] **Step 2: Owner-only route set.** Create `backend/v2/interfaces/admin/owner_gate.py` exporting `OWNER_ONLY_ROUTE_PATHS: frozenset[tuple[str, str]]` of `(METHOD, full_path)` pairs under `/api/v2/admin`, and switch each listed route's dependency from `require_persona("admin")` to `require_owner()`:

  *billing_routes.py*: PUT `/billing/settings/platform-fallback`; PUT `/billing/settings/invoice-schedule`; POST `/enrollments/withdrawal-credit/approve` (the approve route at ~:389; preview stays admin); POST `/payments/refund`; POST `/payments/{id}/discount`; PUT+DELETE `/enrollments/{id}/tuition-discount`; POST `/payments/{id}/undo-paid`; GET `/finance/payouts`; GET `/finance/revenue`; GET `/finance/tuition-discounts`; invoice POST `.../adjustments`; invoice POST `.../void`; invoice POST `.../refund`.
  *billing_products_routes.py*: POST, PATCH, DELETE (GET stays admin).
  *payout_period_routes.py*: every route. *payroll_routes.py*: every route. *coach_pay_rate_routes.py*: every route.
  *reports_routes.py*: session-economics, projected-income, kpis, refunds, revenue-by-category, deposit-slip, `/reports/{name}.csv`. (dashboard, enrollment-funnel, attendance-trends, coach-utilization stay admin.)
  *audit_routes.py*: GET `/audit-logs`.
  *academy_routes.py*: PATCH `/academy/fees`; POST `/academy/gateway/stripe/connect-link`; DELETE `/academy/gateway/stripe/connect`. (GET fees, GET gateway stay admin; the Stripe callback keeps no auth dep.)
  *session_type_routes.py*: POST `/billing-enrollments/{id}/override`.
  *sessions_routes.py*: POST `/enrollments/{id}/fee`.

  Everything else stays `require_persona("admin")`, explicitly including: expenses CRUD, `/payments` list/feed/last-by-family, mark-paid, record-payment, generate-monthly, send, charge-autopay, invoice lines add/remove, reconcile/reconciliation/webhooks, billing-setup routes, dues routes, session types create/edit (price is part of class setup; revisit later), directory reads/invites.

- [ ] **Step 3: Role-grant rule.** In `directory_routes.py`: remove the `enable_owner_role` check at ~:191. In `add_user_role`, `remove_user_role`, `update_user_role`, and `create_user`, when the requested/target role is `admin` or `owner` and `"owner" not in claims.roles`, raise `HTTPException(403, detail="Only the academy owner can grant or revoke admin and owner roles")`. Extend the self-demotion guard to `owner` (an owner cannot remove their own owner role). Put the rule in one helper `ensure_can_assign_role(claims, role)` in `owner_gate.py` and call it from all four handlers.

- [ ] **Step 4: Fixtures.** In `tests/interface/conftest.py` change `_admin_claims()` to `roles=("admin", "owner")` and make `_make_admin_app` default claims `("admin", "owner")` (this mirrors what migration 0165 does to every existing admin). Add `_admin_only_claims()` with `roles=("admin",)`. Run `cd backend && .venv/bin/pytest v2/tests -n auto -q --tb=short` — expect green; fix any test that hard-codes `roles=("admin",)` for a now-owner route by switching it to `_admin_claims()`.

- [ ] **Step 5: Tests.**
  `test_owner_gate_policy.py` (structural): enumerate the real app's routes via `tests/_route_paths.py`; for every `(method, path)` in `OWNER_ONLY_ROUTE_PATHS` assert the route exists and its dependant chain includes `require_owner`'s `_dep` (inspect `route.dependant` recursively for a callable whose `__qualname__` contains `require_owner`); for every other `/api/v2/admin` route assert it does NOT. Also assert the set is non-empty and contains `("POST", "/api/v2/admin/payments/refund")`.
  `test_owner_admin_split.py` (interface, using `_make_admin_app` with `_admin_only_claims()`): admin-only → 404 on `POST /api/v2/admin/payments/refund`, `GET /api/v2/admin/finance/revenue`, `GET /api/v2/admin/audit-logs`, `GET /api/v2/admin/payroll/2026-09`; admin-only → 200 on `GET /api/v2/admin/finance/expenses` and `GET /api/v2/admin/payments` (stub the use cases the way neighbouring tests do); admin-only → 403 on `POST /api/v2/admin/users/{id}/roles` with `{"role": "admin"}` and 200-path (or whatever the existing success code is) with `{"role": "coach"}`; owner → allowed to grant `admin`. Owner cannot remove own `owner` role (existing self-guard status code).

- [ ] **Step 6: Lint + commit.** `cd backend && .venv/bin/ruff format v2 && .venv/bin/ruff check v2 && .venv/bin/pytest v2/tests -n auto -q --tb=short`. Commit: `feat(auth): owner role gates money-governance routes; admins keep operations`.

---

### Task 2 (backend): migration 0165 and local seed

**Files:**
- Create: `backend/v2/migrations/0165_grant_owner_to_existing_admins.py`
- Modify: `backend/scripts/seed_local.py` (~:1584 admin roles)
- Create: `backend/v2/tests/unit/test_migration_0165.py` (or the folder neighbouring migration tests use)

- [ ] **Step 1:** Migration module with `version = "0165_grant_owner_to_existing_admins"` and `async def up(db)`: for every `academy_memberships` doc with `"admin"` in `roles` and `"owner"` not in `roles`, `$addToSet: {roles: "owner"}`; mirror into the legacy `users` doc for the same user (`$addToSet roles owner`) matching how `mongo_user_repo._modify_roles` dual-writes. Idempotent. Log counts.
- [ ] **Step 2:** Test with the in-memory/mongomock pattern the other migration tests use: two memberships (admin, coach) → only the admin one gains owner; running twice changes nothing.
- [ ] **Step 3:** Seed: the local seeded admin gets `roles: ["admin", "owner"]` in both places; add one **admin-only** seeded user (`ops@…`) so the split is visible in dev. Check `frontend/e2e/specs/local-auth-inventory.spec.ts:23-34` comment stays accurate (update it).
- [ ] **Step 4:** Commit: `feat(identity): migration 0165 grants owner to existing admins; seed an admin-only user`.

---

### Task 3 (frontend): owner awareness in the admin shell

**Files:**
- Modify: `frontend/lib/auth/coach-supervisor.ts` (+ `isOwner(roles)`), its `coach-supervisor.node-test.mjs`
- Modify: `frontend/lib/auth/use-persona-auth.ts` (add `isOwner: boolean` to state)
- Modify: `frontend/components/admin/screen-meta.ts` (`ownerOnly?: true` on items; `OWNER_ONLY_ROUTE_PREFIXES`; pure `navForRoles(nav, isOwner)`), new `screen-meta.test.ts`
- Modify: `frontend/app/(admin)/layout.tsx` (filter nav, role label Owner/Admin, owner-only route panel)
- Modify: `frontend/app/(admin)/admin/page.tsx` (hide revenue tile + chart unless owner; show "Dues to chase" tile from the existing dashboard/attention data or keep two tiles)
- Modify: `frontend/app/(admin)/admin/users/[userId]/page.tsx:36`, `frontend/app/(admin)/admin/users/new/page.tsx:10` (role options: admin sees coach/parent; owner sees admin/coach/parent/owner)
- Modify: `frontend/app/(admin)/admin/payments/page.tsx` and invoice detail dialogs: hide Refund / Discount / Void / Undo-paid actions unless owner, with a one-line hint "Owner only"
- Modify: `frontend/app/(admin)/admin/settings/page.tsx`: hide Fees and Gateway panels unless owner
- Modify: `frontend/e2e/specs/admin-shell.spec.ts` (ADMIN_ME → roles ["admin","owner"]; add ADMIN_ONLY_ME; new tests)

- [ ] **Step 1:** `isOwner(roles: readonly UserRole[]): boolean` in `coach-supervisor.ts`; node test.
- [ ] **Step 2:** `ownerOnly: true` on nav items: `/admin/payouts`, `/admin/reports`, `/admin/audit-logs`. `OWNER_ONLY_ROUTE_PREFIXES = ["/admin/payouts", "/admin/reports", "/admin/audit-logs", "/admin/coach-payslip", "/admin/session-economics"]` (note `/admin/reports/dues` is NOT owner-only: special-case exact prefix `/admin/reports/dues` as allowed). `navForRoles(ADMIN_NAV, isOwner)` returns groups with owner-only items removed (drop empty groups). `isOwnerOnlyRoute(pathname)`. Vitest tests for both, including the dues exception.
- [ ] **Step 3:** `usePersonaAuth` exposes `isOwner` (`currentUser.roles.includes("owner")`). Layout: `const nav = navForRoles(ADMIN_NAV, auth.isOwner)` passed to both sidebar trees; role label `auth.isOwner ? "Owner" : "Admin"`; when `isOwnerOnlyRoute(pathname) && !auth.isOwner` render an `OwnerOnlyPanel` (data-testid `owner-only-panel`, copy: "This page is for the academy owner. Ask them if you need a change here.") instead of `{children}`.
- [ ] **Step 4:** Dashboard: revenue tile and chart render only when `auth.isOwner`; expose `isOwner` to the page via `usePersonaAuth("admin")` (already used) or a tiny context from the layout if the page doesn't call it.
- [ ] **Step 5:** Users pages role options by `isOwner`; payments/invoice money actions hidden unless owner; settings money panels hidden unless owner. Keep testids unchanged for owner.
- [ ] **Step 6:** `pnpm test:unit && pnpm lint && pnpm typecheck`.
- [ ] **Step 7:** e2e in `admin-shell.spec.ts`: change `ADMIN_ME.roles` to `["admin","owner"]`; add `ADMIN_ONLY_ME` (`roles: ["admin"]`) and a `stubAdminBff` option to use it. New tests: (a) admin-only user: nav (via `openAdminNav`) has no `admin-nav-reports`, `admin-nav-coach-payouts`, `admin-nav-audit-log` testids, dashboard has no revenue tile (find its testid or text "Revenue"), visiting `/admin/reports` shows `owner-only-panel`, `/admin/reports/dues` does not; (b) owner user: those nav items present and `/admin/reports` mounts as before; (c) admin-only user on `/admin/users/new` sees no "admin" option. Run `pnpm exec playwright test e2e/specs/admin-shell.spec.ts --project=chromium-desktop --project=chromium-mobile`.
- [ ] **Step 8:** Commit: `feat(admin): owner-aware shell — owner-only nav, dashboard revenue, money actions and routes`.

---

### Task 4 (orchestrator): release note, structural checks, PR

- Release note `docs/release-notes/2026-09-05-owner-admin-role-split.md` with the three sections; Deploy notes must state migration 0165 does NOT run on boot (`V2_RUN_MIGRATIONS_ON_BOOT` is false in prod, #629) and must be applied by hand before or right after deploy, and that until it runs existing admins lose money screens (so run it FIRST).
- Push, open PR, watch CI.
