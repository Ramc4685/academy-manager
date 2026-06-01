# Active Student Waiver Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require one active waiver for all active students, show waiver status on Students, send reminders to unsigned families, and let parents digitally accept the waiver.

**Architecture:** Keep the workflow in v2 onboarding/admin/parent boundaries. Admin status remains derived from the required active template plus latest student signatures. Parent acceptance writes immutable `waiver_signatures` rows and does not mutate published templates.

**Tech Stack:** FastAPI, Pydantic, Motor/MongoDB, Next.js App Router, React Query, Tailwind, pytest, Playwright.

---

### Task 1: Backend Status And Reminder Contract

**Files:**
- Modify: `backend/v2/contexts/onboarding/application/use_cases/admin_waivers.py`
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `backend/v2/interfaces/admin/waiver_routes.py`
- Modify: `backend/v2/interfaces/admin/deps.py`
- Modify: `backend/v2/composition/admin.py`
- Test: `backend/v2/tests/interface/test_admin_waivers.py`
- Test: `backend/v2/tests/interface/conftest.py`

- [ ] Add a failing interface test for `POST /api/v2/admin/waivers/reminders` that seeds one pending row, one outdated row, and one signed row, then asserts two students are targeted and one parent reminder is recorded.
- [ ] Implement `SendAdminWaiverReminders` in `admin_waivers.py`. It should call `ListAdminWaivers.execute()`, filter `pending` and `outdated`, group children by parent id, and call a reminder sender port.
- [ ] Add admin response DTOs for reminder count, targeted students, skipped students, and blocked/sent state.
- [ ] Wire the route and fake/composed dependencies.
- [ ] Run `pytest v2/tests/interface/test_admin_waivers.py -q` from `backend/`.

### Task 2: Parent Waiver Read And Acceptance

**Files:**
- Create: `backend/v2/contexts/onboarding/application/use_cases/parent_student_waivers.py`
- Create: `backend/v2/interfaces/parent/waiver_routes.py`
- Modify: `backend/v2/interfaces/parent/views.py`
- Modify: `backend/v2/interfaces/parent/router.py`
- Modify: `backend/v2/interfaces/parent/deps.py`
- Modify: `backend/v2/composition/parent.py`
- Test: `backend/v2/tests/interface/test_parent_waivers.py`

- [ ] Add failing tests for parent waiver status and acceptance. A parent with two active students and no signatures should see both as `pending`; after POST accept, the response should show both as `signed`.
- [ ] Implement a parent waiver use case that loads the required template, active children for the parent, and latest signatures.
- [ ] Implement acceptance by writing one `WaiverSignature` per pending/outdated active student with current template id/hash, signer email/name, timestamp, IP, and user agent.
- [ ] Expose `GET /api/v2/parent/waivers/current` and `POST /api/v2/parent/waivers/accept`.
- [ ] Run `pytest v2/tests/interface/test_parent_waivers.py -q` from `backend/`.

### Task 3: Students Waiver Status

**Files:**
- Modify: `backend/v2/contexts/enrollment/application/use_cases/admin_directory.py`
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `frontend/lib/api/admin.ts`
- Modify: `frontend/app/(admin)/admin/students/page.tsx`
- Modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx`
- Test: `backend/v2/tests/contract/test_admin_directory_mongo_student_repo.py`
- Test: `backend/v2/tests/interface/test_admin_directory.py`

- [ ] Add failing backend tests asserting student list/detail include waiver status.
- [ ] Extend admin student summary/detail DTOs with `waiver_status`, `waiver_signed_at`, and `waiver_version`.
- [ ] Batch compute latest signature status in `MongoStudentRepository` using required active template and latest signatures/legacy acceptances.
- [ ] Add a Waiver column to the Students table and a waiver status panel to student detail.
- [ ] Run focused backend tests and `cd frontend && pnpm typecheck`.

### Task 4: Admin And Parent UI

**Files:**
- Modify: `frontend/lib/api/admin.ts`
- Modify: `frontend/lib/api/parent.ts`
- Modify: `frontend/app/(admin)/admin/waivers/page.tsx`
- Create: `frontend/app/(parent)/parent/waivers/page.tsx`
- Modify: `frontend/app/(parent)/parent/dashboard/page.tsx`
- Test: focused Playwright or route smoke where available.

- [ ] Add API clients for admin reminders and parent waiver read/accept.
- [ ] Add `Send reminders` to the Waivers page, disabled when no pending/outdated rows exist.
- [ ] Build `/parent/waivers` with current waiver text, child statuses, and accept action.
- [ ] Add a parent dashboard action card pointing to `/parent/waivers`.
- [ ] Run `cd frontend && pnpm typecheck` and a focused local browser check on admin waivers, students, and parent waivers.

### Task 5: Verification And Handoff

**Files:**
- Modify: `test_result.md`

- [ ] Run focused backend waiver/student tests.
- [ ] Run frontend typecheck.
- [ ] Run local smoke or browser verification against `http://blno.localhost:3001`.
- [ ] Update `test_result.md` with implemented behavior, verification, and any skipped checks.
- [ ] Check `git status --short --branch` and `git diff` before final response.
