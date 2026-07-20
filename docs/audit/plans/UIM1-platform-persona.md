# UIM1 — Platform/tenant-admin persona UI
Status: TODO
Size: L · Depends on: DS1-3 recommended (Modal/FormField/Toast primitives) · Tracker: ../TRACKER.md

## User value
The entire platform-operator domain (~35 backend routes across 5 route files in `backend/v2/interfaces/platform/`) has zero UI. Tenant onboarding, lifecycle, platform billing, governance (GDPR exports/deletions), support access, and audit review are today only reachable via curl. A `(platform)` surface makes multi-tenant SaaS operable and is a precondition for selling to a second academy.

## Backend status (verified — routes, DTO fields)
All routes exist and are mounted via `backend/v2/interfaces/platform/router.py` (aggregate mount; slices included with `_include_if_available`). Wrong persona ⇒ **404** (`require_platform_admin` / `require_platform_operator` raise 404, not 403).

Auth (from `backend/v2/shared/auth/claims.py`): platform capability lives in `claims.platform_roles` (`platform_admin`, `platform_support`). `AuthClaims.has_role()` deliberately excludes platform roles; `is_platform_admin()` checks `"platform_admin" in platform_roles`; `has_platform_role("platform_support")` for support tier. `/me` (`backend/v2/interfaces/me_routes.py`) already returns `platform_roles: tuple[str, ...]` — the frontend guard can use it.

**bootstrap_routes.py** (`/platform` prefix):
- `POST /platform/academies/bootstrap` → `BootstrapAcademyResponse {academy_id, slug, primary_domain, owner_user_id, membership_id, owner_role, created, default_records}` (admin-only)
- `POST /platform/tenants` (create) · `GET /platform/tenants/{academy_id}/status` · `GET .../health` (`TenantHealthResponse {academy_id, status, servable, reason, plan_code, limits{max_students,max_coaches,max_locations}}`) · `POST .../activate|suspend|cancel|reactivate` (suspend/cancel take `{reason}`) · `PATCH .../plan` (`{plan_code, limits}`). All lifecycle mutations return `TenantLifecycleResponse {academy_id, display_name, slug, primary_domain, status, servable, reason, plan_code, limits, status_reason, updated_by}`. Status/health reads allow `platform_support`; mutations are admin-only.
- **Gap: there is no `GET /platform/tenants` list route.** Phase 1 needs one (see Backend to build).

**billing_routes.py** (`/platform/billing`, all admin-only):
- `GET /plans` → `list[PlatformPlanResponse {plan_id, code, display_name, monthly_price_cents, currency, limits{max_active_students,max_locations,max_staff_members}, status, stripe_price_id, created_at, updated_at}]`
- `PUT /plans/{plan_id}` (`UpsertPlanRequest`)
- `GET /tenants/{academy_id}/subscription` → `TenantSubscriptionResponse {subscription_id, academy_id, plan_id, billing_status, trial_status, cancellation_status, stripe_customer_id, stripe_subscription_id, current_period_start/end, trial_started_at, trial_ends_at, cancel_at_period_end, cancelled_at, created_at, updated_at}`
- `POST /tenants/{academy_id}/trial` (`{plan_id, trial_ends_at}`) · `/activate-subscription` · `/schedule-cancellation` · `/cancel-now` · `/check-limits` (`PlatformUsageRequest {active_students, locations, staff_members}` → `PlanLimitReportResponse {…, allowed, violations[]}`)

**governance_routes.py** (`/platform/governance`): POST+GET pairs for `tenant-exports` (`TenantExportResponse {export_request_id, status, include_pii, reason, retention_policy, pii_handling_policy, artifact_metadata, artifact_expires_at, …}`), `tenant-deletions`, `student-data-deletions`, `support-access-grants` (+ `POST .../{id}/revoke`), `support-impersonation-requests` (`SupportImpersonationResponse {impersonation_request_id, status, impersonation_enabled, approval_required, session_token, …}` — create allows `platform_support`), and `GET /requests/{request_id}/status`. Lists accept `?academy_id=` filter and allow platform_support.

**audit_routes.py**: `GET /platform/audit-events?academy_id=&limit=(1-500)` → `{events: [{audit_event_id, actor_user_id, actor_membership_id, academy_id, platform_actor_role, action, entity_type, entity_id, before_snapshot, after_snapshot, request_id, ip_address, created_at}]}` (admin or support).

**connect_routes.py**: `POST /platform/academies/{academy_id}/connect/onboarding` (`{refresh_url, return_url}`) → `{academy_id, stripe_account_id, onboarding_url, status}` (admin-only; 503 if `app.state.platform_connect_onboarding` not composed).

**Flag**: `enable_platform_routes` defaults **True** (`backend/v2/shared/config/settings.py:57`) but `_validate_launch_settings` (settings.py:234-239) **raises at boot if `env=prod` AND `tenancy_mode=single_academy` AND flag on**. To enable in prod: either flip `tenancy_mode=multi_academy` (requires no `primary_academy_id` constraint semantics change) or run a separate platform-ops deployment with `enable_platform_routes=true` and multi_academy mode. The plan ships the UI dark-launched behind the frontend guard regardless; document the ops decision in the Phase 1 PR.

## Frontend to build (pages/components/queries — concrete)
New route group `frontend/app/(platform)/` with its own `layout.tsx`:
- Guard: fetch `/me` (existing `lib/api/me.ts getCurrentUser`) and require `platform_roles` non-empty; else redirect to `/post-login`. Distinguish admin vs support to hide mutation buttons for support.
- Nav: Tenants · Billing · Governance · Audit.
- New per-persona client `frontend/lib/api/platform.ts` using `apiFetch` from `lib/api/client.ts`.
- New `queryKeys.platform.*` namespace in `frontend/lib/query/keys.ts` (`tenants()`, `tenantStatus(id)`, `tenantHealth(id)`, `plans()`, `subscription(academyId)`, `governance(kind, academyId?)`, `auditEvents(academyId?, limit?)`) — extend the `QueryKey` union type at the bottom of the file.
- Client components + TanStack Query v5 throughout (per AGENTS.md).

Pages:
- `/platform` (redirect to `/platform/tenants`)
- `/platform/tenants` — list + "Create tenant" + "Bootstrap academy" modals
- `/platform/tenants/[academyId]` — status/health cards, lifecycle action buttons (suspend/cancel require reason dialog), plan editor, subscription card + trial/activate/cancel actions, Connect onboarding button (opens returned `onboarding_url`), limit-check widget
- `/platform/billing` — plans table + upsert-plan form
- `/platform/governance` — tabs: Exports · Deletions · Student-data deletions · Support access · Impersonation; each = list table + create dialog; grants get Revoke action
- `/platform/audit` — event table with academy filter + limit, expandable before/after snapshots

## Backend to build (if any — route, use case, tests, manifest registration)
- `GET /platform/tenants` list route in `bootstrap_routes.py` returning `list[TenantLifecycleResponse]`; add `list_tenants()` to `TenantLifecycleService` (`backend/v2/contexts/platform/application/use_cases/tenant_lifecycle.py`) + repo method. Operator-readable (admin + support). Interface test in `backend/v2/tests/interfaces/` covering 404-for-wrong-persona and shape.
- **Manifest**: every new `page.tsx` must be registered in `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` — `test_inventory_manifest_matches_frontend_app_route_tree` in `backend/v2/tests/unit/test_audit_inventory_manifest.py` asserts manifest routes == app routes, and each entry needs `role/source/workflows/controls{buttons,inputs,modals}/states/risk_edges/acceptance`. NOTE: `role` must be in `{admin, authenticated, coach, parent, proxy, public}` — a `platform` role value requires extending `allowed_roles` in that test (do it in Phase 1 PR).

## Implementation steps (phased — each phase one PR)
1. **Phase 1 — shell + tenants**: `(platform)` layout/guard, `lib/api/platform.ts`, query keys, tenant list route (backend), tenant list/detail pages with lifecycle actions, manifest entries + allowed_roles extension. Document prod-enablement decision.
2. **Phase 2 — platform billing**: plans page, subscription card + trial/activate/cancellation/limit-check on tenant detail.
3. **Phase 3 — governance**: 5-tab governance page, all create/list/revoke flows, support-role gating of buttons.
4. **Phase 4 — audit viewer + Connect**: audit table, Connect onboarding trigger on tenant detail.

## Files to change/create
- Create: `frontend/app/(platform)/layout.tsx`, `frontend/app/(platform)/platform/page.tsx`, `.../platform/tenants/page.tsx`, `.../platform/tenants/[academyId]/page.tsx`, `.../platform/billing/page.tsx`, `.../platform/governance/page.tsx`, `.../platform/audit/page.tsx`, `frontend/lib/api/platform.ts`
- Modify: `frontend/lib/query/keys.ts`, `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`, `backend/v2/tests/unit/test_audit_inventory_manifest.py` (allowed_roles), `backend/v2/interfaces/platform/bootstrap_routes.py` (+ list route), `backend/v2/contexts/platform/application/use_cases/tenant_lifecycle.py` (+ repo), new interface test file

## Verification
- `pytest backend/v2/tests/unit/test_audit_inventory_manifest.py` and new interface tests green
- Frontend: `pnpm typecheck && pnpm lint`; e2e smoke: platform_admin token sees tenant list; admin-persona token gets 404 from `/platform/*`; support user sees lists but no mutation buttons
- Backend boot check: prod single-academy settings still refuse `enable_platform_routes=true`

## Risks / rollback
- Impersonation/support-access are sensitive: keep buttons admin-gated client-side AND rely on server 404s; audit recorder is auto-wired in `get_tenant_governance`.
- 503s when `app.state.*` use cases aren't composed (e.g. Connect) — surface as "not configured" empty states, not errors.
- Rollback: route group is additive; deleting `(platform)` dir + manifest entries reverts cleanly. Backend list route is additive.

## PR checklist (release note · TRACKER.md · plan Status → DONE)
- [ ] Release note per phase
- [ ] Update TRACKER.md row UIM1 (status/PR)
- [ ] Flip this plan's Status to DONE after Phase 4
