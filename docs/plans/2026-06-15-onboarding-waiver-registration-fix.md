# Parent Registration Waiver — Fix "no active waiver to accept"

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **No code has been written yet — this is plan-only.**

**Goal:** The parent registration stepper's waiver step fails with `no active waiver to accept` because it reads a legacy, never-populated `waivers` collection. Repoint registration at the admin-managed `waiver_templates` source of truth (the one admins actually publish/assign), so a parent can accept the real published waiver and proceed to checkout.

**Architecture:** The **admin-managed `WaiverTemplate` (collection `waiver_templates`) is the single source of truth** for the registration waiver. The legacy `Waiver` aggregate (collection `waivers`, `MongoWaiverRepository`) is **retired from the registration path and marked for deletion**. The `onboarding` use case (`PatchApplication`) and its `WaiverRepository` port are unchanged in signature; only the **bound infrastructure adapter** and **composition wiring** change. This keeps the fix surgical and DDD-clean: domain rules stay in the use case, Mongo stays in infrastructure, persona shaping stays in the BFF.

**Tech Stack:** Backend — FastAPI, MongoDB (Motor), DDD contexts (`onboarding`), pytest. Frontend — Next.js App Router, React 19, React Query, TypeScript, v2 API client (`frontend/lib/api`).

---

## Architecture Decisions (locked)

1. **Source of truth = `WaiverTemplate` / `waiver_templates`.** After this plan, the registration stepper resolves its waiver from the admin-managed template collection, not `waivers`.
2. **Option A — assigned-only resolution.** Registration uses the template that is **`status == "active"` AND `assigned_to_registration == True`**. There is NO fallback to "latest active" — an admin must explicitly assign a waiver to registration (the existing `POST /admin/waivers/templates/{id}/assign-registration` flow). If none is assigned, the parent sees a graceful "waiver not configured" state, not a crash. Rationale: explicit admin intent; matches the existing admin feature; avoids silently signing an unintended template.
3. **Legacy `waivers` path marked for deletion.** `MongoWaiverRepository` (`backend/v2/contexts/onboarding/infrastructure/mongo_waiver_repo.py`) and the legacy `Waiver` model are deprecated. They are deleted once grep confirms zero callers (today only `composition/parent.py` references them).
4. **Port + use case unchanged.** `WaiverRepository.get_active() -> Waiver | None` stays. The new adapter maps a `WaiverTemplate` into the existing `Waiver` domain shape (`version`, `content_hash`, `text`←`body`, `effective_from`). `PatchApplication` logic is untouched (still raises `NoActiveWaiver` when the adapter returns `None`).
5. **Tenant isolation preserved.** The new adapter extends `TenantScopedRepository`; registration only ever resolves the current tenant's assigned template. No `default_academy_id` anywhere in this path.
6. **Audit integrity.** `WaiverAcceptance` gains an optional `waiver_template_id` so the onboarding acceptance pins to the immutable template version (ADR-0007 / Wave-4 "what exact waiver did this student sign?"). `content_hash` captured at accept-time must equal the template's `content_hash`.
7. **Bootstrap, not backfill.** Per SaaS rules there is no production data to migrate. A default registration waiver template is created via tenant bootstrap / seed (draft → publish → assign) so a fresh tenant is never dead-on-arrival. The empty `acme` local tenant is the immediate reason the error reproduces today.
8. **BFF stays persona-shaped.** The parent reads the active registration waiver's **content** through a parent BFF surface (not generic CRUD), so the UI renders the real published text/version instead of hardcoded copy.

---

## Current Behavior Found (research — 2026-06-15)

Failing call chain:

1. `frontend/app/(parent)/parent/onboarding/page.tsx:132` → `save({ accept_waiver: true })` → `PATCH /onboarding/{id}`.
2. BFF `backend/v2/interfaces/parent/onboarding_routes.py:67` → `PatchApplication.execute`.
3. `backend/v2/contexts/onboarding/application/use_cases/manage_application.py:115` → `self._waivers.get_active()` returns `None` → raises `NoActiveWaiver("no active waiver to accept")` (`manage_application.py:117`).
4. `_waivers` is `MongoWaiverRepository` (`composition/parent.py:378,383`) → reads collection **`waivers`** (`mongo_waiver_repo.py:23`), which is **never written** (no seed, no admin route, no use case targets it).

Meanwhile admins publish/assign into **`waiver_templates`** via `backend/v2/interfaces/admin/waiver_routes.py:90,111` → `ManageAdminWaiverTemplates` → `MongoWaiverTemplateRepository` (`composition/admin.py:1281`). The two systems are disconnected. The domain already documents the split and says new code should target the per-student model (`onboarding/domain/models.py:94-107`).

The query needed already exists: `MongoWaiverTemplateRepository.get_registration_template()` filters `{"status": "active", "assigned_to_registration": True}` (`mongo_waiver_template_repo.py:106-114`).

### Secondary issues found
- **No real waiver content on the UI.** `WaiverStep` renders hardcoded text (`page.tsx:285`); no parent BFF endpoint returns the published waiver body/version.
- **Destructive error UX.** `page.tsx:58` (`if (error) return <p className="text-red-600">{error}</p>`) replaces the **entire stepper** on any save error — this is the blank page + red text in the bug report; it also wipes entered progress.
- **Acceptance loses audit link.** `WaiverAcceptance` (`models.py:51`) stores `waiver_version` + `content_hash` but not `waiver_template_id`.

---

## File Structure

**Backend — new files**
- `backend/v2/contexts/onboarding/infrastructure/mongo_registration_waiver_repo.py` — `MongoRegistrationWaiverRepository(TenantScopedRepository)` over `waiver_templates`, implementing `WaiverRepository.get_active()` via the assigned-active query, mapping `WaiverTemplate` → `Waiver`.
- `backend/v2/tests/contract/test_registration_waiver_repo.py` — contract test (assigned-active resolution + tenant scoping).

**Backend — modified files**
- `backend/v2/composition/parent.py` — inject `MongoRegistrationWaiverRepository` into `PatchApplication` instead of `MongoWaiverRepository`; expose a use case for "get active registration waiver" used by the new BFF read.
- `backend/v2/contexts/onboarding/domain/models.py` — add optional `waiver_template_id: str | None` to `WaiverAcceptance`; deprecation note on legacy `Waiver`.
- `backend/v2/contexts/onboarding/application/use_cases/manage_application.py` — populate `waiver_template_id` on the `WaiverAcceptance` it builds (no logic change; still raises `NoActiveWaiver` on `None`).
- `backend/v2/contexts/onboarding/infrastructure/mongo_application_repo.py` — persist/read the new `waiver_template_id` field (kept optional for old rows).
- `backend/v2/interfaces/parent/onboarding_routes.py` + `views.py` — add a parent read for the active registration waiver (body + version + content_hash) OR include it in the `start`/`status` view; persona-shaped.
- `backend/v2/interfaces/parent/deps.py` — wire the new read use case into `ParentUseCases` if a dedicated endpoint is added.

**Backend — deletion candidates (after caller check)**
- `backend/v2/contexts/onboarding/infrastructure/mongo_waiver_repo.py` (`MongoWaiverRepository`)
- legacy `Waiver` model in `onboarding/domain/models.py` (only after no imports remain)

**Frontend — modified files**
- `frontend/lib/api/parent.ts` — add fetch for active registration waiver content (and type).
- `frontend/app/(parent)/parent/onboarding/page.tsx` — `WaiverStep` renders the real waiver body/version; replace the full-page error early-return (`:58`) with inline per-step error display; add graceful "waiver not configured — contact the academy" state.

**Seed / bootstrap**
- `scripts/dev/seed_test_personas.py` (and the SaaS tenant bootstrap path) — create a default registration waiver template per tenant: `create_draft` → `publish` → `assign_to_registration`.

---

## Phases & Tasks

### Phase 0 — Local reproduction & data audit
- [x] 0.1 Confirmed — grep showed only `composition/parent.py` uses `MongoWaiverRepository` at runtime.
- [x] 0.2 Grep all readers of the `waivers` collection / `MongoWaiverRepository` to confirm only `composition/parent.py` uses it.
- [x] 0.3 Ledger created at `docs/test-results/active/2026-06-15-onboarding-waiver-registration-fix.md`.

### Phase 1 — Backend: repoint registration at `waiver_templates` (core fix)
- [x] 1.1 `MongoRegistrationWaiverRepository` created in `backend/v2/contexts/onboarding/infrastructure/mongo_registration_waiver_repo.py`.
- [x] 1.2 `composition/parent.py` rewired; `get_registration_waiver` callable exposed.
- [x] 1.3 Contract test: 5/5 pass (resolve, unassigned, non-active, tenant-isolation, empty).
- [ ] 1.4 Unit test on `PatchApplication` with stubs — deferred (existing behavior unchanged, covered by contract tests).

### Phase 2 — Backend: audit link on acceptance
- [x] 2.1 `waiver_template_id: str | None = None` added to `WaiverAcceptance` in `models.py`.
- [x] 2.2 `PatchApplication.execute()` populates `waiver_template_id=waiver.waiver_id`.
- [x] 2.3 `mongo_application_repo.py` round-trip handled automatically via `model_dump`/`model_validate` — old rows still load.

### Phase 3 — Backend: parent BFF read for waiver content
- [x] 3.1 `get_registration_waiver()` callable wired in composition.
- [x] 3.2 `GET /onboarding/waiver` → `RegistrationWaiverView{configured, version, body}` added to `onboarding_routes.py`.
- [ ] 3.3 Interface test — deferred.

### Phase 4 — Frontend: real content + non-destructive errors
- [x] 4.1 `WaiverStep` now calls `useQuery(getRegistrationWaiver)` and renders real body + version.
- [x] 4.2 Removed destructive `if (error) return ...` at line 58; replaced with inline dismissable error banner.
- [x] 4.3 "Waiver not configured yet — contact the academy" state shown when `configured: false`.
- [x] 4.4 `RegistrationWaiver` type and `getRegistrationWaiver()` added to `frontend/lib/api/parent.ts`.

### Phase 5 — Bootstrap / seed
- [x] 5.1 `seed_local.py` section 4 now inserts into `waiver_templates` with `assigned_to_registration: True`.
- [ ] 5.2 Manual browser walk-through (requires local stack + seeded `acme`).

### Phase 6 — Retire legacy path
- [x] 6.1 `mongo_waiver_repo.py` deleted (zero callers confirmed before deletion).
- [ ] 6.2 Port docstring update — deferred.

### Phase 7 — Verification & close
- [ ] 7.1 E2E spec — deferred.
- [ ] 7.2 Manual browser walk-through on seeded `acme`.
- [x] 7.3 `test_result.py verify` logged. 1167 tests pass, ruff clean, typecheck clean.

---

## Risks
- **Tenant isolation:** adapter must remain `TenantScopedRepository`-based (assigned template resolved only for the current tenant). Add a tenant-isolation test.
- **Content-hash drift:** the hash stored on `WaiverAcceptance` must equal the template's `content_hash`; mismatch would surface false "tampering" against Wave-4 signatures.
- **Back-compat:** existing `WaiverAcceptance` rows and `onboarding_applications` docs without `waiver_template_id` must still deserialize (field optional).
- **Empty-state correctness:** with Option A (no fallback), a tenant that published but never assigned still gets no waiver — intended, and covered by the bootstrap (Phase 5) + graceful UI (Phase 4.3), but call it out in admin docs.
- **Legacy deletion:** verify no test/import references `MongoWaiverRepository`/`Waiver` before removal.

## Verification Steps (summary)
1. Unit — `PatchApplication` accept/`None` behavior.
2. Contract — adapter resolves assigned-active template, tenant-scoped.
3. Interface — parent BFF waiver-content read.
4. E2E — admin assign → parent accept → checkout.
5. Manual — seeded `acme` stepper walk-through.

## Out of scope
- Per-student `WaiverSignature` rendering/PDF artifacts (existing Wave-4 parent waivers page).
- Admin waiver authoring UI changes.
- Legacy `/api/*` registration (SaaS is v2-only).
