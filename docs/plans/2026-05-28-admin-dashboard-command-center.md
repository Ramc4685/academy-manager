# Admin Dashboard Command Center Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn `/admin` into a daily operator dashboard that includes current-month profit, cash, dues, today sessions, and actionable follow-up.

**Architecture:** Keep this frontend-first by composing existing admin BFF calls: sessions, payments, revenue, attention, registrations, waitlist, and reports dashboard. Use the richer reports dashboard only for month snapshot metrics; keep deep P&L charts and exports on `/admin/reports`.

**Tech Stack:** Next.js App Router, React Query, TypeScript, existing Rally design-system components, Playwright E2E.

---

### Task 1: Add RED dashboard profit coverage

**Files:**
- Modify: `frontend/e2e/specs/admin-shell.spec.ts`

**Step 1:** Add an E2E case that stubs `/api/v2/admin/reports/dashboard` with current-month `net_profit_cents`, `cash_collected_cents`, `outstanding_dues_cents`, and unpaid payroll.

**Step 2:** Assert `/admin` shows `Month profit`, the formatted profit value, `Cash collected`, and `Outstanding dues`.

**Step 3:** Run the focused Playwright spec and confirm it fails because the current dashboard does not render month profit.

### Task 2: Implement command-center dashboard

**Files:**
- Modify: `frontend/app/(admin)/admin/page.tsx`

**Step 1:** Fetch `getAdminReportsDashboard(currentMonthKey())`, `listAdminRegistrations()`, and `listGlobalWaitlist()` alongside the existing attention, sessions, payments, and revenue calls.

**Step 2:** Replace the KPI strip/chart-first layout with:
- current-month financial snapshot: month profit, cash collected, outstanding dues, payroll unpaid
- today sessions lane
- prioritized action queue
- registrations/intake lane
- recent payments lane

**Step 3:** Keep existing `data-testid="admin-dashboard"` and `data-testid="admin-dashboard-attention"` stable.

### Task 3: Verify

**Files:**
- Modify: `test_result.md`

**Step 1:** Run `cd frontend && pnpm typecheck`.

**Step 2:** Run focused Playwright for `admin-shell.spec.ts`.

**Step 3:** Run browser/rendered QA on `/admin` with desktop and mobile-tolerant viewport if local stack is available.

**Step 4:** Update `test_result.md` with what changed, checks run, and skipped checks.
