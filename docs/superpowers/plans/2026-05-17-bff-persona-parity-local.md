# BFF Persona Parity Local Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local v2 BFF + DDD app usable for admin, coach, and parent persona smoke flows.

**Architecture:** Keep Firebase as authentication and Mongo as authorization/source-of-truth. Add persona-shaped admin directory reads, tighten admin session DTO contracts, and connect frontend screens to v2 BFF APIs without moving business rules into React.

**Tech Stack:** FastAPI, Motor/MongoDB, Firebase Auth emulator, Next.js App Router, TanStack Query, Playwright/browser validation.

---

### Task 1: Admin Directory BFF

**Files:**
- Modify: `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py`
- Create: `backend/v2/contexts/enrollment/application/use_cases/admin_directory.py`
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`
- Create: `backend/v2/interfaces/admin/directory_routes.py`
- Modify: `backend/v2/interfaces/admin/deps.py`
- Modify: `backend/v2/interfaces/admin/router.py`
- Modify: `backend/v2/composition/admin.py`
- Test: `backend/v2/tests/interface/test_admin_directory.py`

- [ ] Add Mongo-backed admin user and student directory queries.
- [ ] Expose `GET /api/v2/admin/users?role=coach|parent|admin` and `GET /api/v2/admin/students`.
- [ ] Verify admin gets real local Mongo users/students and non-admin personas are rejected by the existing admin dependency.

### Task 2: Admin Frontend Uses Real Directories

**Files:**
- Modify: `frontend-next/lib/api/admin.ts`
- Modify: `frontend-next/app/(admin)/admin/users/page.tsx`
- Modify: `frontend-next/app/(admin)/admin/students/page.tsx`
- Modify: `frontend-next/app/(admin)/admin/sessions/page.tsx`
- Modify: `frontend-next/app/(admin)/admin/sessions/[id]/page.tsx`

- [ ] Replace placeholder users/students screens with BFF-driven tables.
- [ ] Use the real coach list when creating sessions.
- [ ] Use the real student list when adding roster entries.

### Task 3: Admin Session Contract Fixes

**Files:**
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `backend/v2/interfaces/admin/sessions_routes.py`
- Modify: `backend/v2/interfaces/admin/waitlist_routes.py`
- Modify: `backend/v2/composition/admin.py`

- [ ] Include enrolled/waitlist counts in admin session rows.
- [ ] Return enrollment fields consumed by the frontend (`full_name`, `enrolled_at`) without dropping existing fields.
- [ ] Return waitlist data under both `entries` and `waitlist` so existing tests and frontend code both work.

### Task 4: Coach And Parent Local Smoke Data

**Files:**
- Local MongoDB only, no destructive writes.
- Modify: `test_result.md`

- [ ] Seed one local student, one active enrollment, one attendance record, and one payment if missing.
- [ ] Confirm coach today reads through `/api/v2/coach/today`.
- [ ] Confirm parent onboarding/payments and admin payments use the same local data.

### Task 5: Verification

**Commands:**
- `backend/.venv/bin/python -m pytest backend/v2/tests/interface/test_admin_directory.py backend/v2/tests/interface/test_admin_sessions.py backend/v2/tests/interface/test_admin_waitlist.py -q`
- `backend/.venv/bin/python -m pytest backend/v2/tests -q`
- `cd frontend-next && pnpm typecheck && pnpm build`
- Browser/Playwright smoke on `http://localhost:3001/login` for admin, coach, and parent.

- [ ] Record actual command/browser results in `test_result.md`.
