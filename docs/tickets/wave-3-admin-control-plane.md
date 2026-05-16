# Wave 3 — Admin Control Plane

**Goal:** Admin sessions / enrollments / waitlist / billing-admin / coaching-admin / finance / comms fully on v2. Desktop-first, mobile-tolerant.

**Prerequisite:** Wave 2 exit gate cleared.

**Exit gate (from plan):**
1. Admin pages fully on v2.
2. Lighthouse PWA ≥ 90 on admin desktop.
3. Mobile-tolerant (works, not optimized).

**Estimate:** 3–4 weeks.

---

## Backend

### W3-01 — Enrollment write slice (admin paths)
- **Type:** Backend / Application
- **Estimate:** 10h
- Use cases: `CreateSession`, `EditSession`, `CancelSession`, `EditRoster (add/remove student)`, `TransferEnrollment`, `PauseEnrollment`, `ResumeEnrollment`. Cancellation emits `EnrollmentCancelled` (drives Wave 2 waitlist promotion handler).

### W3-02 — Waitlist write slice (admin paths)
- **Type:** Backend / Application
- **Estimate:** 4h
- `JoinWaitlist`, `PromoteFromWaitlist` (admin trigger), `SkipFromWaitlist`, `RemoveFromWaitlist`. FIFO order preserved.

### W3-03 — Coaching admin reads
- **Type:** Backend / Application
- **Estimate:** 3h
- `ListAttendanceForSession`, `ListLessonPlansForSession`, `ListProgressNotesForStudent`. Read-only admin views.

### W3-04 — Finance use cases (inside Billing, marked `# FINANCE`)
- **Type:** Backend / Application
- **Estimate:** 6h
- `RecordExpense`, `ListExpenses`, `ListCoachPayouts`, `AcademyRevenueQuery`. Carve-out markers per ADR-0006 trigger.

### W3-05 — Shared comms module
- **Type:** Backend / Application
- **Estimate:** 5h
- `shared/comms/` (small enough not to earn a context). `SendBroadcast`, `SendDM`, `ListMessages`. Persisted in `messages` / `announcements` collections.

### W3-06 — Admin BFF routes
- **Type:** Backend / Interface
- **Estimate:** 12h
- `interfaces/admin/{enrollment,billing,coaching,waitlist,finance,comms}_routes.py` + `views.py`. Persona-shaped (admin can see academy-wide fields; parent/coach surfaces never).

### W3-07 — Admin BFF security tests
- **Type:** Backend / Test
- **Estimate:** 4h
- Coach/parent hitting admin paths → 404.

### W3-08 — Admin migrations + indexes
- **Type:** Backend / DB
- **Estimate:** 2h
- `messages`, `announcements`, `expenses`, `payouts` indexes; `audit_logs` collection.

## Frontend — Admin route group

### W3-09 — Admin shell + sidebar nav
- **Type:** Frontend / UI
- **Estimate:** 6h
- `app/(admin)/layout.tsx`. Sidebar, top bar, dark mode preserved. Desktop-first; collapse to drawer on mobile.

### W3-10 — Admin sessions page (calendar + table)
- **Type:** Frontend / UI
- **Estimate:** 8h
- FullCalendar dynamically imported. Table view also available. Create / edit / cancel flows.

### W3-11 — Admin enrollments + roster page
- **Type:** Frontend / UI
- **Estimate:** 6h
- Table with bulk actions, transfer dialog, pause/resume.

### W3-12 — Admin waitlist page
- **Type:** Frontend / UI
- **Estimate:** 4h
- FIFO list with promote/skip/remove.

### W3-13 — Admin billing page
- **Type:** Frontend / UI
- **Estimate:** 5h
- Payment history table; refund dialog. Stripe receipt links.

### W3-14 — Admin finance page (revenue + payouts + expenses)
- **Type:** Frontend / UI
- **Estimate:** 6h
- Recharts dynamically imported. Marked `# FINANCE` in component file comments.

### W3-15 — Admin comms page
- **Type:** Frontend / UI
- **Estimate:** 4h
- Broadcast composer, DM threads.

### W3-16 — Lighthouse + size baselines for admin
- **Type:** Ops
- **Estimate:** 2h
- Run perf-baseline procedure per W1A-01 for the admin route group; set budgets.

### W3-17 — Playwright E2E for admin
- **Type:** Test / E2E
- **Estimate:** 8h
- 10 specs: session create, enrollment confirm, waitlist promote, refund issue, view payout, attendance audit, message broadcast, calendar render, chart render, mobile-tolerable render.

## Ops

### W3-18 — Cutover canary 10% → 100%
- **Type:** Ops
- **Estimate:** 4h elapsed
- Same shape as W1A/W2.

## Exit Checklist

- [ ] W3-01 … W3-08 backend merged.
- [ ] W3-09 … W3-17 frontend merged.
- [ ] Lighthouse PWA ≥ 90 on admin desktop.
- [ ] Admin route group bundle within budget set in W3-16.
- [ ] Cutover documented in `docs/cutover-w3-admin.md`.
