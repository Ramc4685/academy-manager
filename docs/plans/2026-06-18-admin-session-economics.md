# Admin Session Economics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an admin-visible `/admin/session-economics` page that shows monthly revenue, payment collection, coach cost, expense allocation, and expected profit by session.

**Architecture:** Keep the business calculation in the v2 admin BFF. Add a focused reports query that reads sessions, active enrollments, invoices/payments, payout period lines, and monthly expenses, then returns presentation-ready rows for the frontend.

**Tech Stack:** FastAPI, MongoDB/Motor-style async repositories, Pydantic response models, Next.js App Router, React Query, Tailwind.

---

### Task 1: Backend Response Contract

**Files:**
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `backend/v2/interfaces/admin/reports_routes.py`
- Test: `backend/v2/tests/interface/test_admin_reports_dashboard.py`

**Step 1:** Write a failing route/model test for `GET /api/v2/admin/reports/session-economics?period=2026-04`.

**Step 2:** Add `AdminSessionEconomicsResponse` and row/summary models.

**Step 3:** Wire a new admin report route guarded by `require_persona("admin")`.

**Step 4:** Run the focused interface test and confirm it passes.

### Task 2: Backend Calculation

**Files:**
- Modify: `backend/v2/composition/admin.py`
- Modify: `backend/v2/interfaces/admin/deps.py`
- Test: `backend/v2/tests/application/test_admin_reports_dashboard.py`

**Step 1:** Write a failing application test for one monthly priced session with active enrollments and April occurrences.

**Step 2:** Calculate session economics per session:
- active enrolled students
- payable occurrence count
- expected revenue per occurrence = monthly fee × enrolled students ÷ payable occurrences
- expected revenue total
- paid and unpaid amounts from current invoice/payment data where safely attributable to the session
- coach payroll from payout period lines or zero when not generated
- allocated rent and other expenses by expected revenue share
- expected profit and margin

**Step 3:** Add summary totals and blocked/empty-state notes when source data is missing.

**Step 4:** Run focused backend tests.

### Task 3: Frontend Page

**Files:**
- Create: `frontend/app/(admin)/admin/session-economics/page.tsx`
- Modify: `frontend/components/admin/screen-meta.ts`
- Modify: `frontend/lib/api/admin.ts`

**Step 1:** Add TypeScript client types and API function.

**Step 2:** Add the Money nav item and route metadata.

**Step 3:** Build the `/admin/session-economics` page with month filter, summary KPIs, and a dense session table.

**Step 4:** Run frontend typecheck and lint.

### Task 4: Verification Ledger

**Files:**
- Modify: `docs/test-results/active/2026-06-18-admin-session-economics.md`

**Step 1:** Record implementation notes.

**Step 2:** Record focused backend and frontend verification results.

**Step 3:** Record skipped manual checks or remaining risks.
