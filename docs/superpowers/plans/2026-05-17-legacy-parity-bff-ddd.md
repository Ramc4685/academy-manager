# Legacy Parity BFF/DDD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the remaining high-use legacy admin, coach, and parent workflows into persona-shaped v2 BFF routes backed by DDD use cases.

**Architecture:** Keep Firebase as authentication and Mongo as authorization. Add BFF endpoints only for persona workflows, keep orchestration in context application use cases, and keep Mongo/Stripe details in infrastructure/composition.

**Tech Stack:** FastAPI, Motor/MongoDB, Firebase Auth emulator, Stripe fake gateway locally, Next.js App Router, TanStack Query, Playwright.

---

### Task 1: Admin Payment Operations

**Files:**
- Create: `backend/v2/contexts/billing/application/use_cases/admin_payment_ops.py`
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py`
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `backend/v2/interfaces/admin/billing_routes.py`
- Modify: `backend/v2/interfaces/admin/deps.py`
- Modify: `backend/v2/composition/admin.py`
- Modify: `frontend-next/lib/api/admin.ts`
- Modify: `frontend-next/app/(admin)/admin/billing/page.tsx`
- Test: `backend/v2/tests/interface/test_admin_billing_ops.py`

- [ ] Generate monthly payments from active enrollments.
- [ ] Mark manual payments paid.
- [ ] Apply discounts.
- [ ] Undo manual paid payments while blocking Stripe-linked rows.

### Task 2: Admin Enrollment Movement

**Files:**
- Modify: `backend/v2/contexts/enrollment/application/use_cases/admin_writes.py`
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_enrollment_writer.py`
- Modify: `backend/v2/interfaces/admin/sessions_routes.py`
- Modify: `frontend-next/app/(admin)/admin/sessions/[id]/page.tsx`
- Test: `backend/v2/tests/interface/test_admin_sessions.py`

- [ ] Transfer an active enrollment to another session.
- [ ] Record move history in Mongo.
- [ ] Keep capacity reservation correct.

### Task 3: Pause Requests

**Files:**
- Create: `backend/v2/contexts/enrollment/application/use_cases/pause_requests.py`
- Create: `backend/v2/contexts/enrollment/infrastructure/mongo_pause_request_repo.py`
- Add parent/admin BFF routes.
- Add parent/admin screens for request and approval.

- [ ] Parent requests a one-month pause for an active enrollment.
- [ ] Admin approves/declines.
- [ ] Approved periods are skipped by billing generation.

### Task 4: Parent Autopay

**Files:**
- Add parent BFF routes for subscription checkout and customer portal.
- Add Stripe gateway methods for subscription checkout/customer portal.
- Extend parent payments page with autopay controls.

- [ ] Parent can start autopay for an enrollment.
- [ ] Parent can open billing portal.
- [ ] Webhook updates subscription status.

### Task 5: Coach Lesson Plans And Progress Notes

**Files:**
- Add coaching context use cases and Mongo repositories for lesson plans/progress notes.
- Add coach BFF routes for session detail notes.
- Extend parent progress route to read real progress notes.

- [ ] Coach creates a lesson plan/progress note.
- [ ] Parent sees child progress notes only for own children.

### Task 6: Reports, Audit, And Dues Follow-up

**Files:**
- Add admin report BFF CSV endpoints or download descriptors.
- Add audit log list route.
- Add dues follow-up safety-blocked local endpoint.

- [ ] Admin can view/export revenue and pending payments.
- [ ] Admin can see audit log rows.
- [ ] Local/test email remains blocked.

---

**Current execution choice:** implement Task 1 first because it unblocks the largest missing admin billing surface and has clear local verification.
