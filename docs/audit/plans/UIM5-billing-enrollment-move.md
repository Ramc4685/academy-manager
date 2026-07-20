# UIM5 — Billing-enrollment move/override UI
Status: TODO
Size: M · Depends on: UIM4 (session-type picker/list + query key) · Tracker: ../TRACKER.md

## User value
Moving a student between session types (with correct proration + Stripe invoice) and overriding a student's price are done today by ops via curl or not at all. Admin gets safe, previewed billing changes; coaches get a read-only proration preview to advise parents without billing power.

## Backend status (verified — routes, DTO fields)
**Admin** (`backend/v2/interfaces/admin/session_type_routes.py`, persona `admin`):
- `:94` `GET /billing-enrollments?student_id=&parent_id=` → `StudentBillingEnrollmentList {enrollments: StudentBillingEnrollmentView[]}`; view = `{enrollment_id, student_id, parent_id, session_type_id, stripe_subscription_id, billing_start_date, status: "active"|"paused"|"cancelled"|"transferred_out", override_price_cents, enrolled_at, updated_at}` (views.py:261-275)
- `:109` `POST /billing-enrollments/{enrollment_id}/move` — body `MoveBillingEnrollmentRequest {to_session_type_id, move_date, period_start, period_end, reason? ≤500}` (all three datetimes REQUIRED — admin UI must compute the calendar-month period of move_date, like the coach route's `_default_period` does server-side) → `MoveBillingEnrollmentResponse {enrollment, proration: SessionTypeProrationView {credit_cents, charge_cents, net_cents, remaining_days, total_days, proration_ratio, from_session_type_id, to_session_type_id, policy_version}, stripe_invoice_id}`. Executes the move AND may create a Stripe invoice — this is a money-touching mutation.
- `:132` `POST /billing-enrollments/{enrollment_id}/override` — body `{override_price_cents: int|null ≥0}` (null clears the override) → updated `StudentBillingEnrollmentView`

**Coach** (`backend/v2/interfaces/coach/billing_enrollment_routes.py`, persona `coach`):
- `:97` `GET /coach/billing-enrollments?session_id=` (session_id REQUIRED; 403 if coach not assigned to the session) → `list[CoachBillingEnrollmentView {enrollment_id, student_id, session_type_id, session_type_name, status, billing_start_date, override_price_cents}]`
- `:149` `GET /coach/billing-enrollments/{enrollment_id}/move/preview?to_session_type_id=&move_date=` → `ProrationPreviewView {credit_cents, charge_cents, net_cents, from_session_type_id, to_session_type_id}` — no side effects; 403 unless coach is assigned to a session the student is enrolled in
- `:198` `POST .../move` — **always 403 by design** ("coach billing changes are disabled; admin approval is required"). The coach UI must NOT offer an apply button; semantics = preview-and-refer-to-admin.

## Frontend to build (pages/components/queries — concrete)
**Admin — student detail billing tab** (`frontend/app/(admin)/admin/students/[studentId]/page.tsx`, existing `billing` tab; extract into a component per MT5 rather than growing the 3000-line page):
- Query: `GET /billing-enrollments?student_id=` → key `queryKeys.admin.billingEnrollments: (studentId: string) => ["admin","billing-enrollments", studentId]`.
- Enrollment rows show session type name (join via `queryKeys.admin.sessionTypes()` from UIM4), status, effective price (override badge when `override_price_cents != null`).
- **Move dialog**: target session-type select (active types only), move date picker (default today; derive `period_start`/`period_end` = first day of move month / first day of next month), reason field; on submit show returned proration breakdown + `stripe_invoice_id` in a success state. Two-step confirm since it invoices.
- **Override dialog**: price input (dollars→cents) with explicit "Clear override" action sending `null`.
- Mutations invalidate `billingEnrollments(studentId)` and `studentDetail(studentId)`.

**Coach — preview flow** on the coach session roster surface (`frontend/app/(coach)/coach/sessions/[id]/page.tsx`):
- "Billing" affordance per roster student: fetch `/coach/billing-enrollments?session_id=`, key `queryKeys.coach.billingEnrollments: (sessionId: string) => ["coach","billing-enrollments", sessionId]`.
- Preview drawer: pick target session type (needs a coach-readable session-type list — reuse `session_type_name` values present in the enrollment list; if a full list is needed, note that coaches have no session-types route and keep the picker limited to types seen in the roster, or add a coach route later), show credit/charge/net from `.../move/preview`. Copy states "changes are applied by an admin" — no apply button.
- API fns in `frontend/lib/api/coach.ts` + admin fns in `frontend/lib/api/admin.ts` (or `lib/api/v2/billing-enrollments.ts`), all via `apiFetch`.

## Backend to build (if any — route, use case, tests, manifest registration)
None required. No new frontend routes (both surfaces are existing pages) → manifest JSON only needs the existing `/admin/students/[studentId]` and `/coach/sessions/[id]` entries extended with the new workflows/modals/acceptance lines (keep `test_audit_inventory_manifest.py` count invariants: acceptance ≥ workflows and ≥ risk_edges).
Optional follow-up (out of scope): coach-readable `GET /coach/session-types` if the preview picker proves too limited.

## Implementation steps (phased if L; each phase one PR)
1. **PR 1 — admin**: billing tab enrollment list + move + override dialogs, query keys, manifest entry update.
2. **PR 2 — coach**: roster billing preview drawer, manifest entry update.

## Files to change/create
- Modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx` (mount extracted panel), `frontend/app/(coach)/coach/sessions/[id]/page.tsx`, `frontend/lib/api/admin.ts`, `frontend/lib/api/coach.ts`, `frontend/lib/query/keys.ts`, `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`
- Create: `frontend/components/admin/student-billing-enrollments-panel.tsx`, `frontend/components/coach/billing-preview-drawer.tsx`

## Verification
- `pnpm typecheck && pnpm lint`; manifest test green
- Manual/e2e: move shows proration matching preview; `net_cents` sign rendering (credit vs charge) correct; override clear returns row to catalog price; coach preview for an unassigned session 403s and renders an access-denied state; coach POST move never offered

## Risks / rollback
- Money-touching: move creates a Stripe invoice — two-step confirm + display `policy_version` and `stripe_invoice_id` in the result for auditability. Test against Stripe sandbox before enabling in prod.
- Period derivation must match backend proration expectations (calendar month) — copy `_default_period` semantics exactly.
- Rollback: UI-only; hide the dialogs.

## PR checklist (release note · TRACKER.md · plan Status → DONE)
- [ ] Release note
- [ ] Update TRACKER.md row UIM5
- [ ] Plan Status → DONE
