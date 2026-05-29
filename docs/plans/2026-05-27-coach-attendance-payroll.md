# Coach Attendance Payroll Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the BLNO spreadsheet payout fallback with the existing occurrence-based payout engine, adding coach/assistant attendance so payouts are based on who actually worked each session.

**Architecture:** Coaching owns coach attendance and payout calculation rules; Enrollment owns session occurrences; Finance owns persisted payout periods. Add a small coach-attendance write model in Coaching, expose coach self check-in and admin override APIs, then teach `ComputeCoachPayout` to pay present/admin-confirmed coach attendance rows before falling back to legacy occurrence attribution.

**Tech Stack:** FastAPI v2 BFF, Mongo/Motor repositories, Pydantic domain models, Next.js admin/coach pages, pytest, ruff, pnpm typecheck/lint.

**Current scope note:** per the 2026-05-27 direction, the implemented slice prioritizes admin marking of coach presence per session occurrence. Coach self check-in remains planned but is deferred until the admin workflow is validated.

---

### Task 1: Add coach-attendance domain and repository

**Files:**
- Modify: `backend/v2/contexts/coaching/domain/models.py`
- Modify: `backend/v2/contexts/coaching/application/ports.py`
- Create: `backend/v2/contexts/coaching/application/use_cases/mark_coach_attendance.py`
- Modify: `backend/v2/contexts/coaching/infrastructure/mongo_attendance_repo.py`
- Test: `backend/v2/tests/application/test_coach_attendance_payroll.py`
- Test: `backend/v2/tests/contract/test_coach_attendance_repo.py`

**Steps:**
1. Write failing tests for coach self check-in and admin override upsert keyed by `(occurrence_id, coach_id)`.
2. Implement `CoachAttendance` with `status`, `role`, `rate_override_minor`, `note`, `marked_by`, `marked_at`.
3. Add Mongo repository methods `upsert_coach_attendance`, `list_for_occurrences`, and `find_for_occurrence_coach`.
4. Verify focused tests pass.

### Task 2: Feed coach attendance into payout calculation

**Files:**
- Modify: `backend/v2/contexts/coaching/domain/payout.py`
- Modify: `backend/v2/contexts/coaching/application/use_cases/compute_payout.py`
- Modify: `backend/v2/composition/admin.py`
- Test: `backend/v2/tests/application/test_coach_payout.py`

**Steps:**
1. Write failing tests showing absent coach is not paid and assistant present with rate override is paid.
2. Extend `PayableOccurrence` with optional `coach_attendance` payroll rows.
3. Update `ComputeCoachPayout` to prefer coach-attendance rows when present; otherwise retain old completed-occurrence attribution behavior.
4. Update Mongo payable occurrence adapter to load attendance rows for the period.
5. Verify payout tests pass.

### Task 3: Add coach/admin APIs

**Files:**
- Modify: `backend/v2/interfaces/coach/views.py`
- Create or modify: `backend/v2/interfaces/coach/attendance_routes.py`
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `backend/v2/interfaces/admin/sessions_routes.py`
- Modify: `backend/v2/interfaces/admin/deps.py`
- Modify: `backend/v2/composition/admin.py`
- Test: `backend/v2/tests/interface/test_coach_attendance.py`
- Test: `backend/v2/tests/interface/test_admin_sessions.py`

**Steps:**
1. Add coach `POST /api/v2/coach/session-attendance` for self check-in.
2. Add admin `PATCH /api/v2/admin/session-occurrences/{id}/coach-attendance` for present/absent/admin-confirmed rows and notes.
3. Include coach attendance rows in admin occurrence list response.
4. Verify interface tests pass.

### Task 4: Wire the UI to the existing payout periods

**Files:**
- Modify: `frontend/lib/api/admin.ts`
- Modify: `frontend/lib/api/coach.ts`
- Modify: `frontend/app/(coach)/coach/sessions/[id]/page.tsx`
- Modify: `frontend/app/(admin)/admin/sessions/[id]/page.tsx`
- Modify: `frontend/app/(admin)/admin/payouts/page.tsx`
- Modify: `frontend/app/(admin)/admin/coach-payslip/page.tsx`

**Steps:**
1. Add a coach “Mark myself present” action on the coach session page.
2. Add admin payroll controls on the session occurrence table for coach status, assistant, rate override, and note.
3. Change payout views to show generated payout periods/lines; remove the expected-revenue fallback from `MongoPayoutRepository` after the UI is wired.
4. Verify browser paths for BLNO sessions, payouts, and payslip.

### Task 5: Update BLNO local data and verification notes

**Files:**
- Modify: `backend/scripts/apply_blno_mongo.py` if bundle collection list changes
- Modify: `.local/blno/mongo_documents/_mongo_import_bundle.json` locally only if needed
- Modify: `test_result.md`

**Steps:**
1. Seed coach rates and initial coach attendance for BLNO test occurrences only when explicitly importing reviewed local data.
2. Generate payout periods for BLNO after attendance is marked.
3. Record verification in `test_result.md`.
