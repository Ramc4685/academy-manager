# Parent Session Catalog Checkout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parent onboarding should select a real BFF-provided session and create checkout with a server-derived price, not a pasted session id or client-provided amount.

**Architecture:** Add a parent-shaped read use case in the Enrollment context for available sessions, expose it through the Parent BFF, and keep Stripe checkout orchestration in Billing/Onboarding composition. The frontend remains presentation-focused: it displays BFF session options and submits only the application id plus return URLs.

**Tech Stack:** FastAPI, Motor/MongoDB, Pydantic, Firebase-authenticated BFF routes, Next.js App Router, TanStack Query, TypeScript.

---

### Task 1: Parent Session Catalog Read Model

**Files:**
- Modify: `backend/v2/contexts/enrollment/application/ports.py`
- Create: `backend/v2/contexts/enrollment/application/use_cases/list_parent_available_sessions.py`
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_session_repo.py`

- [ ] **Step 1: Add an application use case returning parent-safe session options**

Create `ListParentAvailableSessions` with DTO fields: `session_id`, `title`, `location`, `start_at`, `end_at`, `capacity`, `enrolled_count`, `available_seats`, `amount_cents`.

- [ ] **Step 2: Add repository support**

Add `available_for_parent_catalog()` to the session query port and Mongo repo. The Mongo implementation must stay tenant-scoped, exclude cancelled sessions, include future sessions, calculate active enrollment count per session, and read price from `amount_cents`, `monthly_price_cents`, or `monthly_price` dollars.

- [ ] **Step 3: Add focused tests**

Add application/repository-facing tests where existing test helpers support it, otherwise cover through interface tests in Task 3.

### Task 2: Server-Priced Checkout Use Case

**Files:**
- Modify: `backend/v2/interfaces/parent/deps.py`
- Modify: `backend/v2/composition/parent.py`
- Modify: `backend/v2/interfaces/parent/payment_routes.py`
- Modify: `backend/v2/interfaces/parent/views.py`

- [ ] **Step 1: Add a parent composition callable**

Create a callable `start_checkout_for_application(parent_id, application_id, success_url, cancel_url)` in `compose_parent`. It must load the onboarding application, enforce parent ownership via existing `GetApplicationStatus`, require `selected_session_id`, resolve that session from Mongo, derive `amount_cents` server-side, call `StartCheckout`, and transition the application to `CHECKOUT_PENDING` with the returned payment/checkout ids.

- [ ] **Step 2: Update the BFF request shape**

Change `POST /api/v2/parent/checkout/start` so the client no longer sends `amount_cents`. Keep request fields to `application_id`, `success_url`, `cancel_url`.

- [ ] **Step 3: Preserve route error behavior**

Return 404 for missing/unowned application, 422 for application without selected session, and 404/422 for unavailable or unpriced sessions without leaking cross-parent information.

### Task 3: Parent BFF Routes and DTOs

**Files:**
- Create: `backend/v2/interfaces/parent/session_routes.py`
- Modify: `backend/v2/interfaces/parent/router.py`
- Modify: `backend/v2/interfaces/parent/views.py`
- Test: `backend/v2/tests/interface/test_parent_onboarding.py` or a new focused parent BFF test.

- [ ] **Step 1: Add `GET /api/v2/parent/sessions/available`**

Use `require_persona("parent")`, call the parent catalog use case, and return `{ "sessions": [...] }`.

- [ ] **Step 2: Mount the router**

Include the new router under `/api/v2/parent`.

- [ ] **Step 3: Add interface tests**

Cover authenticated parent success, wrong persona 404, checkout request without client amount, and backend-derived payment amount.

### Task 4: Parent Onboarding UI

**Files:**
- Modify: `frontend-next/lib/api/parent.ts`
- Modify: `frontend-next/app/(parent)/parent/onboarding/page.tsx`

- [ ] **Step 1: Add typed API client**

Add `listAvailableParentSessions()` and remove `amount_cents` from the `startCheckout()` payload type.

- [ ] **Step 2: Replace pasted session id with session cards**

Load the catalog in `SessionStep`, show loading/error/empty states, and let the parent select one available session. Keep the existing clean CourtMastr theme, compact form proportions, and accessible buttons.

- [ ] **Step 3: Show selected session in review**

Display the selected session title/date/price when available; fall back to the id if the catalog is not loaded.

### Task 5: Verification and Ledger Update

**Files:**
- Modify: `test_result.md`

- [ ] **Step 1: Run focused backend tests**

Run the focused parent interface/application tests first, then `backend/.venv/bin/python -m pytest backend/v2/tests -q` if the focused suite passes.

- [ ] **Step 2: Run frontend checks**

Run `pnpm typecheck` and `pnpm build` in `frontend-next`.

- [ ] **Step 3: Browser/E2E smoke**

Use the local Firebase emulator, BFF on `8011`, and Next app on `3001` to log in as parent and verify `/parent/onboarding` loads session choices and checkout start no longer sends a client amount.

- [ ] **Step 4: Update `test_result.md`**

Record changed behavior, commands run, pass/fail status, and any remaining parent/admin/coach parity gaps.
