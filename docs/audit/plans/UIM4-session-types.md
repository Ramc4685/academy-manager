# UIM4 — Session-type management UI
Status: DONE (PR #TBD, 2026-07-27)
Size: S · Depends on: none (DS3 FormField/Modal primitives help if available) · Tracker: ../TRACKER.md

## User value
Session types are the pricing catalog (monthly vs per-session, price, overage rate) behind billing enrollments, yet admins cannot see or edit them — the CRUD backend is fully dark. Also unblocks UIM5, whose move flow needs a target session-type picker.

## Backend status (verified — routes, DTO fields)
`backend/v2/interfaces/admin/session_type_routes.py:40-94`, persona `admin`:
- `:40` `GET /session-types` → `SessionTypeList {session_types: SessionTypeView[]}`
- `:49` `POST /session-types` (201) — `CreateSessionTypeRequest {name (1-120), description? (≤500), price_cents ≥0, billing_period: "monthly"|"per_session" (default monthly), overage_rate_cents? ≥0}`
- `:65` `PATCH /session-types/{session_type_id}` — `UpdateSessionTypeRequest` (all optional, incl. `is_active`)
- `:81` `DELETE /session-types/{session_type_id}` (204) — **soft delete** (`soft_delete_session_type`), i.e. archive
- `SessionTypeView {session_type_id, name, description, price_cents, billing_period, overage_rate_cents, is_active, created_at, updated_at}` (`admin/views.py:228-241`)

## Frontend to build (pages/components/queries — concrete)
- Location: settings area — new page `frontend/app/(admin)/admin/settings/session-types/page.tsx`, linked from a card/section on `frontend/app/(admin)/admin/settings/page.tsx` (matches the existing `settings/self-service` child pattern).
- UI: table (name, price formatted from `price_cents`, billing period, overage rate, active badge) with **Create** button (modal form), row **Edit** (modal, PATCH with only changed fields), **Archive** (DELETE with confirm; show archived rows greyed via `is_active=false` filter toggle — note PATCH `is_active: true` can reactivate).
- API fns in `frontend/lib/api/admin.ts` or new `frontend/lib/api/v2/session-types.ts`: `listSessionTypes()`, `createSessionType(body)`, `updateSessionType(id, body)`, `archiveSessionType(id)` via `apiFetch`.
- Query keys (`frontend/lib/query/keys.ts`): `queryKeys.admin.sessionTypes: () => ["admin","session-types"]`. Mutations invalidate `sessionTypes()`; UIM5 consumers reuse this key.
- Forms: validate name required, price ≥ 0 (input in dollars, convert to cents), billing_period select. Use DS FormField/Modal if DS3 has landed; else page-local dialog per current conventions.

## Backend to build (if any — route, use case, tests, manifest registration)
No backend changes. New frontend route `/admin/settings/session-types` **must** be added to `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` (role `admin`, source path, workflows/controls/states/risk_edges/acceptance) or `backend/v2/tests/unit/test_audit_inventory_manifest.py::test_inventory_manifest_matches_frontend_app_route_tree` fails.

## Implementation steps (phased if L; each phase one PR)
1. Single PR: API client fns + query key + page (list/create/edit/archive) + settings link + manifest entry.

## Files to change/create
- Create: `frontend/app/(admin)/admin/settings/session-types/page.tsx`, `frontend/lib/api/v2/session-types.ts`
- Modify: `frontend/app/(admin)/admin/settings/page.tsx` (link), `frontend/lib/query/keys.ts`, `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`

## Verification
- `pnpm typecheck && pnpm lint`; `pytest backend/v2/tests/unit/test_audit_inventory_manifest.py`
- Manual: create → appears; edit price → row updates; archive → disappears from active filter; 204 handled (no JSON parse on empty body)

## Risks / rollback
- Archiving a session type that active billing enrollments reference: backend soft-delete permits it — show a warning copy in the confirm dialog ("existing enrollments keep billing").
- Rollback: additive page; remove route + manifest entry.

## Corrections found during implementation (2026-07-27)
Two assumptions in this plan were stale by the time it was built:

1. **Location.** The plan put the UI at a standalone `/admin/settings/session-types`
   route "matching the existing `settings/self-service` child pattern". UIC7 (#319)
   deleted exactly that pattern — `settings/self-service/page.tsx` is now a
   `redirect()` stub and the panel lives at `?panel=self-service`; UIM9 (#352)
   followed the same tab convention. Shipped as a ninth `SETTINGS_TABS` panel
   (`components/admin/settings/session-types-panel.tsx`) instead. Consequences:
   no new app route, so no `screen-meta.ts` entry, no QA-manifest route row, and
   no route-count bump in the two inventory tests — the `/admin/settings`
   manifest entry was extended instead.
2. **Archived rows are not listable.** The plan assumed the list endpoint returns
   archived types and that `PATCH is_active: true` could reactivate from a
   "show archived" toggle. `GET /admin/session-types` →
   `ListSessionTypes.execute()` → `SessionTypeRepository.list_active()`, whose
   Mongo query hard-filters `{"is_active": True}`
   (`contexts/billing/infrastructure/mongo_session_type_repo.py:39-41`). The
   toggle would have been a no-op and the Reactivate button unreachable, so both
   were dropped and the archive confirmation now says archiving cannot be undone
   from this screen. **Follow-up:** restoring archived types needs an
   `include_archived` query param plus a `list_all()` repo method (5 test fakes
   implement the port) — deliberately not bundled into this S-sized item.

## PR checklist (release note · TRACKER.md · plan Status → DONE)
- [ ] Release note
- [ ] Update TRACKER.md row UIM4
- [ ] Plan Status → DONE
