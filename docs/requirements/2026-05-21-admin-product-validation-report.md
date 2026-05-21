# Admin Product Validation Report

**Date:** 2026-05-21  
**App verified:** `http://localhost:3001` against the running local stack  
**Persona used:** Admin (`ramchand4685@gmail.com`)  
**Purpose:** Convert admin-user feedback into a shareable bug/enhancement report for product and architecture planning.

---

## Executive Summary

The feedback is valid. The current admin experience exposes implementation details, lacks edit/detail workflows in several operational sections, and does not yet model some real academy business rules:

- IDs leak into professional admin screens: student IDs, parent IDs, Mongo IDs, payout IDs, and recipient user IDs.
- Some UI copy describes architecture instead of academy operations: "BFF", "Mongo ID", "monthly cents", "deferred", "loaded students".
- Several pages are read-only where admins naturally expect operational editing: students, users, expenses, waivers, reports, coach payouts.
- Session movement and withdrawal are partly timestamped in data, but pause/resume and simple remove/cancel actions do not capture enough billing/audit context.
- Payments support manual mark-paid, discount, undo for non-Stripe payments, and Stripe webhook updates, but manual partial/over-payment and invoice PDF/receipt handling are not clearly modeled in the admin UI.
- Reports are mostly exports plus a small summary. Admins need on-screen dashboards first, export second.
- Waiver storage is closer to a snapshot model than a complete signed-document workflow. It needs admin access to current templates, signed snapshots, sharing/export, and multiple waiver assignment rules.
- Settings should become the academy configuration source of truth, but the admin shell still hard-codes `Rally Academy`, timezone is free text, fees are global cents instead of session pricing, and email/SMS/payment settings are not operationally connected.

Recommended direction: treat this as the next Admin Control Plane product-depth wave, not a cosmetic cleanup. The UI polish and data-model/API changes should be planned together.

---

## Verification Performed

Local services were already running:

- MongoDB `27017`
- Firebase Auth emulator `9099`
- Backend API `8001`
- Frontend `3001`

I verified the live app with an isolated Playwright script using the real local frontend at `http://localhost:3001`. Pages inspected:

- `/admin/sessions`
- `/admin/sessions/{id}`
- `/admin/students`
- `/admin/users`
- `/admin/payments`
- `/admin/dues`
- `/admin/expenses`
- `/admin/payouts`
- `/admin/reports`
- `/admin/messages`
- `/admin/waivers`
- `/admin/settings` panels: academy, fees, gateway, notify, roles, branding, data

Code evidence was read from:

- `frontend/app/(admin)/admin/**`
- `frontend/components/admin/settings/**`
- `backend/v2/interfaces/admin/**`
- `backend/v2/contexts/**`
- selected legacy routers where v2 has gaps

No behavior changes were made for this report.

---

## Product Principles For Fixes

1. **Professional screens should not show database identifiers.** Internal IDs belong in logs, audit detail, debug drawers, or support-only views.
2. **Admin screens should use academy language.** Avoid BFF, Mongo, cents, deferred, context, workstream, current result set.
3. **Every list that represents an operational object needs a detail/edit path.** Students, parents, coaches, sessions, expenses, waivers, payouts, and invoices need clear drill-down.
4. **Financial and enrollment actions need effective dates and audit context.** Pause, move, withdrawal, substitute coaching, discounts, manual payments, and refunds all affect money.
5. **Reports should be readable in-app.** CSV export is secondary.
6. **Settings should drive the product.** Academy name, timezone, branding, notification policy, payment setup, and session pricing should affect UI, emails, invoices, and exports.

---

## Findings By Section

### 1. Sessions

**User feedback:** No way to edit session name. Need dates for pause, move, withdraw, and remove actions.

**Current behavior verified:**

- Session list shows table/calendar, create session, and cancel session.
- Session detail shows roster actions: pause, move, withdraw, remove.
- No edit action for session title, time, location, capacity, coach, pricing, or name.

**Code evidence:**

- `frontend/app/(admin)/admin/sessions/page.tsx` provides create/cancel but no edit flow.
- `frontend/app/(admin)/admin/sessions/[id]/page.tsx` provides roster actions but no session edit form.
- `backend/v2/interfaces/admin/sessions_routes.py` exposes `POST /sessions`, `DELETE /sessions/{id}`, enrollment transfer, pause, resume, delete/cancel, but no `PATCH /sessions/{id}`.
- `backend/v2/contexts/enrollment/application/use_cases/admin_writes.py` names `EditSession` in the module docstring, but no `EditSession` implementation exists.
- Move history is recorded in `backend/v2/contexts/enrollment/infrastructure/mongo_enrollment_writer.py` with `moved_at`.
- Withdrawal credit approval records `withdrawal_date` through `backend/v2/interfaces/admin/billing_routes.py`.
- Pause uses `update_status(..., "paused")` and does not store `paused_at`, pause effective date, pause reason, billing policy, or actor.

**Assessment:**

- Confirmed bug/enhancement: session edit is missing.
- Confirmed audit gap: move and withdrawal have some date support; pause/resume/remove do not have enough operational history.

**Recommended requirement:**

- Add `EditSession` use case and `PATCH /api/v2/admin/sessions/{session_id}`.
- Add a session edit UI reachable from list and detail.
- Store enrollment lifecycle events as append-only history:
  - `paused_at`, `pause_effective_date`, `pause_reason`, `resume_at`, `resume_effective_date`
  - `moved_at`, `from_session_id`, `to_session_id`, `effective_date`, `reason`
  - `withdrawn_at`, `withdrawal_effective_date`, `credit_preview_id`, `credit_amount`
  - `removed_at`, `remove_reason`, `actor_id`
- Show this history in the student detail and session roster row.
- Reconcile legacy/v2 naming: legacy uses session `name`, while v2 uses `title`. Pick one admin-facing term and bridge the data model explicitly.
- Add enrollment policy settings for pause behavior. Default: pausing a student releases the seat, moves the student to that session's waitlist, stops future billing while paused, and opens the seat for another student. Other configurable options should include hold seat, keep billing, skip billing, and admin-decides-per-pause.
- Moving sessions must capture move date/effective date and trigger prorated billing adjustments for the old and new sessions.

**Priority:** P0 for operational/billing correctness.

---

### 2. Students

**User feedback:** "Loaded students" and "BFF status" should not be visible. Admin expects all students. Need edit student info. Do not show student hash/ID. Clicking student should show parent phone and full details.

**Current behavior verified:**

- Dashboard cards show `Loaded students`, `Active loaded`, `Paused loaded`, and `From BFF status`.
- Student ID/ULID appears under each student name.
- Parent name and email show, but not phone in the table.
- There is no student detail or edit affordance.

**Code evidence:**

- `frontend/app/(admin)/admin/students/page.tsx` renders `Loaded students`, `From BFF status`, and visible `student.student_id`.
- Table has no actions column and no link to a student detail route.

**Assessment:**

- Confirmed UI professionalism bug.
- Confirmed missing operational workflow.

**Recommended requirement:**

- Replace metrics:
  - `Loaded students` -> `Students`
  - `Active loaded` -> `Active`
  - `Paused loaded` -> `Paused`
  - remove `From BFF status`
- Hide `student_id` from the main table.
- Add `/admin/students/{student_id}` with:
  - student profile edit
  - parent/contact details, including phone
  - sessions/enrollments
  - attendance
  - payment status
  - pause/move/withdraw history
  - waiver status
- Add edit capabilities for student name, DOB/age if stored, level, status, notes, parent link/contact.

**Priority:** P0 for admin usability and data maintenance.

---

### 3. Coaches & Parents

**User feedback:** Cannot click/edit coaches and parents. MongoID should not show.

**Current behavior verified:**

- `/admin/users` is a read-only directory.
- It visibly shows a `Mongo ID` column with long IDs.
- Role assignment is hidden in Settings Roles, not naturally in the user profile.

**Code evidence:**

- `frontend/app/(admin)/admin/users/page.tsx` renders `Mongo ID` and `user.user_id`.
- No edit route or action is present.
- `frontend/components/admin/settings/roles-panel.tsx` contains role toggles.

**Assessment:**

- Confirmed UI professionalism bug.
- Confirmed missing user-management workflow.

**Recommended requirement:**

- Remove `Mongo ID` from the directory.
- Add user detail/edit pages:
  - `/admin/users/{user_id}`
  - edit name, email, phone, status, role, linked students, linked sessions
  - for coaches: assigned sessions, pay rule, attendance/payout history
  - for parents: children, balances, messages, waivers
- Move or link role management into the user profile. Settings can retain a role-policy overview.

**Priority:** P0.

---

### 4. Payments

**User feedback:** Why show invoice number? Are invoice PDFs sent? How do manual partial/over-payments work? Can Stripe update the dashboard automatically?

**Current behavior verified:**

- Payments table shows invoice number, student, period, amount, discount, final, status, method.
- Parent technical ID appears under student name.
- Pending manual invoices can be discounted or marked paid.
- Paid non-Stripe rows can be undone.
- Stripe-linked payments require refund workflow.
- The mark-paid dialog does not clearly capture actual amount paid for partial/over-payment.

**Code evidence:**

- `frontend/app/(admin)/admin/payments/page.tsx` shows invoice number and parent ID fallback.
- `backend/v2/contexts/billing/application/use_cases/admin_payment_ops.py` supports monthly invoice generation, mark paid, discount, and undo.
- `backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py` sets `paid_at`, `payment_date`, `payment_method`, and `notes` when marked paid.
- `backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py` blocks undo for Stripe-linked payments.
- `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py` handles Stripe events including checkout completion, invoice paid, invoice failed, payment failed, charge refunded, and subscription changes.
- No clear v2 invoice PDF generation/sending endpoint was found in admin billing. Legacy email reminders exist, but not invoice PDF delivery as an admin workflow.
- Compatibility risk: v2 admin payment listing can expose legacy `_id` values as `payment_id`, but the v2 update lookup path does not clearly convert those string IDs back to `ObjectId`. Manual operations can miss legacy rows unless this is fixed.
- Deployment/API risk: current deployment docs and legacy code reference `/api/webhook/stripe`, while the v2 route is under `/api/v2/parent/webhooks/stripe`. Stripe endpoint configuration needs one canonical production path.

**Assessment:**

- Stripe auto-update is designed through webhooks, assuming Stripe is configured and webhook events arrive.
- Manual payment capture is too simple for real operations.
- Invoice number is useful internally and for parent receipts, but the table should not make it feel like an unexplained technical ID.

**Recommended requirement:**

- Keep invoice number, but rename/present as `Invoice` and make it clickable to invoice detail.
- Hide parent technical IDs from payment rows.
- Add invoice detail:
  - line items
  - due date
  - sent status
  - payment timeline
  - receipt/invoice PDF link if generated
  - Stripe transaction/reference if applicable
- Add manual payment model:
  - `amount_received_cents`
  - `payment_method`
  - `received_at`
  - `reference_number`
  - `notes`
  - `overpayment_policy`: default to account credit, with refund/adjustment as admin override options
  - `partial_payment_remaining_cents`
- Add statuses: pending, partially paid, paid, overpaid/credit, failed, refunded, void.
- Add receipt/invoice delivery requirements:
  - generate invoice PDF when an admin requests it or when sending a reminder email
  - email invoice/receipt/reminder to parent when requested
  - store sent timestamp and provider result
  - downloadable PDF for admin and parent
- Overpayments should automatically become account credits and apply to the next month.
- Add a compatibility test proving manual mark-paid/discount/refund works for both v2-native payment IDs and legacy Mongo `_id` payment rows until legacy data is fully migrated.
- Confirm and document the canonical Stripe webhook endpoint in `DEPLOYMENT.md`.

**Priority:** P0 for payment correctness; P1 for PDF polish.

---

### 5. Dues Follow-up

**User feedback:** Need to select only a few parents and send reminder email.

**Current behavior verified:**

- Page has a single `Send reminders` button.
- No row selection.
- Parent IDs are visible under parent names.

**Code evidence:**

- `frontend/app/(admin)/admin/dues/page.tsx` has only bulk send.
- Legacy reminder route exists in `backend/routers/email_routes.py`, but the v2 admin UX is not selective.
- Legacy reminder API accepts optional `parent_ids`; v2 `POST /dues-reminders` currently has no request body and is all-pending/all-derived.

**Assessment:**

- Confirmed missing selection workflow.

**Recommended requirement:**

- Add row checkboxes and a selected count.
- Add reminder preview before sending.
- Allow filters: due amount, invoice count, session, days overdue, parent.
- Store reminder audit:
  - recipients selected
  - sent/skipped/failed
  - template/version
  - actor
  - timestamp
- Remove parent ID from visible table.

**Priority:** P1.

---

### 6. Expenses

**User feedback:** Can add expenses but cannot edit existing expenses.

**Current behavior verified:**

- Expenses page has `Add expense`.
- Existing rows are read-only.
- No edit/delete/action column.

**Code evidence:**

- `frontend/app/(admin)/admin/expenses/page.tsx` renders add-only UI.
- v2 `backend/v2/interfaces/admin/billing_routes.py` exposes `GET /finance/expenses` and `POST /finance/expenses`; no `PATCH` or `DELETE`.
- Legacy `backend/routers/finance_routes.py` has expense update and soft delete, but v2 admin route has not carried this over.

**Assessment:**

- Confirmed v2 parity gap.

**Recommended requirement:**

- Add v2 update/delete use cases and routes:
  - `PATCH /api/v2/admin/finance/expenses/{expense_id}`
  - `DELETE /api/v2/admin/finance/expenses/{expense_id}` as soft delete
- Add edit dialog and delete confirmation.
- Preserve audit log for category, amount, note, incurred date changes.
- Bridge v2 expense fields with richer legacy fields where needed: description, paid-to, status, notes, and date.

**Priority:** P1.

---

### 7. Coach Payouts

**User feedback:** Do not show coach IDs. Need to understand assignment. Pay should be based on actual sessions coached, including substitutes.

**Current behavior verified:**

- Local v2 page shows no payouts yet.
- Source shows payout rows can display `coach_id` and `payout_id`.
- Existing payout logic is not exposed as a complete v2 workflow.

**Code evidence:**

- `frontend/app/(admin)/admin/payouts/page.tsx` can show `coach_id` and `payout_id`.
- v2 finance model in `backend/v2/contexts/billing/application/use_cases/finance.py` has simple payout read model only.
- Legacy `backend/routers/finance_routes.py` calculates payouts based on sessions assigned to coach; for attendance/session-day basis it counts attendance records or distinct attendance dates for the assigned sessions.
- Coaching attendance stores `marked_by` in `backend/v2/contexts/coaching/infrastructure/mongo_attendance_repo.py`, but current payout design does not clearly assign payable session occurrences to actual coach/substitute.
- Legacy has payout rule, calculate, approve, pay, and undo flows. v2 currently exposes read-only payout listing, so payout administration is not at parity.

**Assessment:**

- Current model is assignment-based, not fully "who actually coached this occurrence" based.
- Substitute coaching needs a first-class concept.

**Recommended requirement:**

- Add `session_occurrence` or `coach_assignment_occurrence` model:
  - scheduled coach
  - actual coach
  - substitute coach
  - occurrence date/time
  - attendance marked by
  - admin override reason
  - payout eligibility
- Coach payout should calculate from actual payable occurrences, not just recurring session owner.
- Adopt this default payout policy:
  - assigned sessions do not create payout by themselves
  - absent sessions are not payable
  - attended sessions are payable
  - substitute coaches are paid for the sessions they actually attend/coach
  - `gross_revenue = sum(session_student_count * session_fee)`
  - `net_after_rent = gross_revenue - total_rent - total_misc`
  - `coach_pool = net_after_rent * coach_pool_percent`
  - `revenue_share = coach_pool * coach_attended_sessions / total_attended_coach_sessions`
  - `base_payout = max(session_floor * coach_attended_sessions, revenue_share)`
  - if `total_attended_coach_sessions == 0`, payout is `0`
- Add admin UI:
  - coach monthly payout detail
  - occurrence list with actual coach/substitute
  - approve payout
  - mark paid
  - export/share payslip
- Hide IDs from the main payout page.

**Priority:** P0/P1 depending on payroll urgency.

---

### 8. Reports

**User feedback:** CSV-only reports are not useful. Need reports visible as dashboards; export is secondary.

**Current behavior verified:**

- Reports page shows a revenue trend summary and export cards.
- Buttons are `Export CSV`.
- Descriptions mention backend contexts.

**Code evidence:**

- `frontend/app/(admin)/admin/reports/page.tsx` uses export-first report cards.
- Legacy exports include revenue, pending payments, attendance, coach payouts, profit, and waivers. v2 report export support is narrower and currently omits profit, payout, and waiver CSV parity.

**Assessment:**

- Confirmed product gap.

**Recommended requirement:**

Build in-app dashboards for:

- Owner finance: revenue collected by month, expenses, rent, misc spend, net profit, coach pool, and payout totals
- Daily operations: pending dues, roster movement, attendance, session fill, waitlist, and coach attendance
- Pending dues by parent/session
- Student count by session/status
- Attendance by session/student/coach
- Coach payout summary
- Expenses and profit
- Waiver compliance
- Enrollment changes: joins, pauses, moves, withdrawals

Each report should support date range/session/coach filters, on-screen table/chart, then export.

Also decide whether unsupported report exports should return `404`/clear UI-disabled states rather than CSV error rows.

**Priority:** P1.

---

### 9. Messages

**User feedback:** Broadcast should allow selecting audience/session. Direct messages should not require recipient user ID; it should search/autofill.

**Current behavior verified:**

- Broadcast sends globally.
- Direct message composer asks for `Recipient user ID`.
- DM thread labels can show sliced recipient ID.

**Code evidence:**

- `backend/v2/shared/comms/messages.py` stores broadcast as `kind="announcement"` with `recipient_id=None`.
- `backend/v2/interfaces/admin/comms_routes.py` accepts only message body for broadcast and `recipient_id` for DM.
- `frontend/app/(admin)/admin/messages/page.tsx` has placeholder and aria-label `Recipient user ID`.
- Legacy messaging has a contact graph check before DM. v2 admin DM currently accepts arbitrary recipient IDs and has no thread IDs, recipient validation, delivery status, or audience segmentation.

**Assessment:**

- Confirmed audience-targeting gap.
- Confirmed admin-unfriendly recipient UX.

**Recommended requirement:**

- Add recipient picker backed by user/student/session search.
- Broadcast audience options:
  - all parents
  - all coaches
  - parents in selected session
  - selected parents/students
  - selected coach group
- Store target scope on announcements:
  - `scope_type`: all/session/role/selected
  - `scope_ids`
  - resolved recipient count
  - delivery status
- Add preview and confirmation for broad sends.
- Add contact/recipient validation so admins select real users and non-admin personas cannot message outside allowed relationships.

**Priority:** P1.

---

### 10. Waivers

**User feedback:** Need to see original waiver/template, signed waiver, share link/export, multiple waivers, and understand industry standard.

**Current behavior verified:**

- Page shows current waiver metadata and per-student signature status.
- No link to waiver template text.
- No signed document link/export/share action.
- No multiple-waiver assignment UI.

**Code evidence:**

- `backend/v2/contexts/onboarding/application/use_cases/admin_waivers.py` explicitly reports signals derived from stored documents and omits expiry/renewal policy because current collections do not store a validity rule.
- `backend/v2/interfaces/admin/waiver_routes.py` exposes read-only list.
- Legacy onboarding stores waiver version, content hash, waiver text/text snapshot during acceptance in `backend/routers/onboarding_routes.py`.
- `frontend/app/(admin)/admin/waivers/page.tsx` is read-only.
- v2 has no admin API to create/edit/publish waiver templates and no signed-document download endpoint.

**Industry/legal standard notes, not legal advice:**

- UETA establishes legal equivalence of electronic records/signatures and paper writings/manual signatures when parties agree to transact electronically, per the Uniform Law Commission summary of UETA ([Uniform Law Commission](https://www.uniformlaws.org/acts/catalog/current/e)).
- ESIGN was enacted to support validity and legal effect of contracts entered electronically, with consumer consent and access requirements for records that otherwise must be provided in writing ([NTIA/FTC ESIGN report](https://www.ntia.gov/report/2001/esign-report-consumer-consent-provision-section-101c1cii)).
- Federal e-signature language defines an electronic signature as an electronic sound, symbol, or process attached to or associated with a record and adopted with intent to sign ([47 CFR § 54.419](https://www.law.cornell.edu/cfr/text/47/54.419)).

**Recommended waiver standard for this product:**

- Store immutable waiver template versions:
  - version
  - title
  - full text
  - content hash
  - effective date
  - retired date
  - required roles/students/sessions
- Store immutable signed snapshots:
  - signer user ID and signer name/email at time of signing
  - student ID covered; waiver compliance is tracked per student, not per family
  - waiver version
  - full text snapshot or durable document reference
  - content hash
  - accepted timestamp
  - IP/user agent/device metadata where appropriate
  - consent language shown
  - PDF/share artifact generated from the snapshot
- Admin UI:
  - view current template
  - create new version
  - assign waiver requirements per student, with bulk assignment helpers by session/program when needed
  - view signed snapshot per student/parent
  - download/share PDF
  - remind pending signers
- Legal counsel should review final waiver language and retention policy before production reliance.

**Priority:** P0 for legal/compliance confidence if waivers are used operationally.

---

### 11. Settings

**User feedback:** Settings should be domain-driven and should control academy display name, emails, timezone, validation, fees per session, Stripe connection, email/SMS options, roles, branding, and data downloads.

**Current behavior verified:**

- Academy settings include display name, timezone, contact email, phone, hours, address.
- Timezone is a free-text field defaulting to `UTC`.
- Sidebar still hard-codes `Rally Academy` and `ADMIN · COURT 7`.
- Fees show `Monthly cents`, `Late fee cents`, `Grace days`.
- Gateway says Stripe Connect not connected and onboarding is deferred.
- Notifications show dues reminders, attendance alerts, daily admin digest; no email/SMS channel policy.
- Roles panel lets admin switch roles inline but is noisy.
- Data panel contains exports and deletion controls are deferred.

**Code evidence:**

- `frontend/components/admin/settings/academy-panel.tsx` uses free-text timezone/contact fields.
- `frontend/components/admin/settings/fees-panel.tsx` exposes cents labels.
- `frontend/app/(admin)/layout.tsx` hard-codes `Rally Academy`.
- `backend/v2/contexts/identity/infrastructure/mongo_academy_repo.py` stores academy defaults including timezone, fees, manual methods, notifications.
- Legacy settings and v2 settings diverge: legacy stores items like Zelle, reminder template, currency, default capacity, and skill prices in `academy_settings`; v2 stores profile, fees, notifications, gateway/manual methods in `academies`.

**Assessment:**

- Settings has the beginning of an academy configuration model but it is not yet fully wired into the product.

**Recommended requirement:**

- Academy profile:
  - display name drives shell brand, emails, invoice PDFs, parent portal, exported reports
  - contact email/phone/address validation
  - timezone dropdown using IANA zones
  - locale/currency
- Session pricing:
  - pricing belongs on session/program/enrollment, not only global monthly cents
  - per-session fee, billing frequency, trial/no-charge flag, proration policy
- Enrollment lifecycle policy:
  - pause behavior options with default `release seat and move student to waitlist`
  - move billing policy with date-based proration
  - withdrawal outcome default `credit`, with refund/credit/admin-adjustment override
- Payment gateway:
  - Stripe connection status
  - test/live indicator
  - webhook health
  - last successful event
  - manual payment methods
- Notifications:
  - email enabled
  - SMS hidden until a provider integration is actually added; this is future scope, not near-term
  - templates per event
  - sender identity from academy profile
- Roles:
  - role changes from user profile with audit and confirmation
  - Settings can show role policy/permissions matrix
- Data:
  - keep downloads here, but reports should remain visual dashboards
  - deletion/retention must be a governed workflow, not a simple button
- Add a migration/bridge decision for legacy `academy_settings` to v2 `academies` before relying on Settings as the production source of truth.

**Priority:** P0 for branding/timezone/fee correctness; P1 for gateway/admin polish.

---

## Cross-Cutting Architecture Gaps

### A. Audit Trail

The app needs a unified operational audit/event timeline for admin actions that affect money, attendance, enrollment, or legal documents. Current behavior has scattered `updated_at`, move history, withdrawal date, audit logs, and payment timestamps, but not a consistent admin-facing lifecycle.

Required event types:

- session_created
- session_edited
- session_cancelled
- student_edited
- parent_edited
- enrollment_paused
- enrollment_resumed
- enrollment_moved
- enrollment_withdrawn
- enrollment_removed
- payment_discounted
- manual_payment_recorded
- invoice_sent
- reminder_sent
- expense_created/edited/deleted
- coach_assignment_changed
- substitute_assigned
- payout_approved/paid
- waiver_signed/template_versioned
- message_broadcast_sent

### B. Search And Selection

Several workflows require choosing people or sessions but currently require IDs or lack selection entirely. Build reusable admin pickers:

- student picker
- parent picker
- coach picker
- session picker
- invoice picker

### C. Detail Pages

The admin control plane needs detail routes:

- `/admin/students/{student_id}`
- `/admin/users/{user_id}`
- `/admin/payments/{payment_id}`
- `/admin/expenses/{expense_id}`
- `/admin/payouts/{payout_id}`
- `/admin/waivers/{waiver_id}` and `/admin/waivers/signatures/{signature_id}`

### D. Hide Internal IDs

Internal IDs can remain available in:

- audit logs
- support/debug drawer
- copied hidden metadata for support
- API responses

They should not appear in normal admin tables.

---

## Suggested Implementation Waves

### Wave A - Professional UI Cleanup

Goal: remove technical leakage without changing domain behavior.

- Hide IDs in Students, Users, Payments, Dues, Payouts, Messages.
- Replace BFF/Mongo/cents/deferred/context labels.
- Wire academy display name into admin shell.
- Rename student metrics.
- Add clear empty states and "coming soon" only where product-approved.

### Wave B - Admin Detail/Edit Workflows

Goal: make core entities maintainable.

- Student detail/edit.
- User detail/edit.
- Session edit.
- Expense edit/delete.
- Payment invoice detail.
- Waiver template/signature detail.

### Wave C - Financial Correctness

Goal: handle real payment and billing operations.

- Manual partial/over-payment.
- Invoice/receipt PDF and email.
- Dues selected reminders.
- Session pricing.
- Pause/move/withdraw billing-effective dates.
- Stripe health/settings visibility.

### Wave D - Coach Payout And Substitution Model

Goal: pay coaches based on actual coached sessions.

- Session occurrence model.
- Substitute assignment.
- Actual coach per occurrence.
- Payout calculation from payable occurrences.
- Payslip and approval flow.

### Wave E - Reports And Waiver Compliance

Goal: make admin insights visible and legal/compliance records usable.

- In-app report dashboards.
- Export from settings/data and report pages as secondary actions.
- Waiver template versioning.
- Signed waiver snapshots and share/export.
- Multi-waiver assignment.

---

## Severity Summary

| Priority | Item |
|---|---|
| P0 | Hide internal IDs and architecture terms from admin UI |
| P0 | Add student/user/session detail and edit workflows |
| P0 | Record effective dates and audit context for pause/move/withdraw/remove |
| P0 | Payment model for manual partial/over-payments and invoice detail |
| P0 | Waiver signed-document/template access if waivers are relied on legally |
| P0/P1 | Coach payout actual-occurrence/substitute model |
| P1 | Selective dues reminders |
| P1 | Expense edit/delete |
| P1 | In-app reports/dashboard views |
| P1 | Settings-driven branding, timezone dropdown, session pricing, Stripe health |

---

## Product Decisions Captured

1. **Paused students:** settings should expose policy options. Default policy: pause releases the seat, moves the student to the session waitlist, stops future billing while paused, and opens the seat for other students.
2. **Session moves:** moving a student must capture the move date/effective date and prorate billing accordingly.
3. **Withdrawals:** outcome is admin-selected; default outcome is account credit.
4. **Invoice PDFs:** generate when requested by admin or when sending a reminder email.
5. **Manual payment methods:** support cash, check, Zelle, Venmo, bank transfer, and other.
6. **Overpayments:** automatically become account credits and apply to the next month.
7. **SMS:** future scope. Hide SMS until a provider integration exists.
8. **Waivers:** waiver compliance is per student.
9. **Reports:** optimize first for owner finance and daily operations.
10. **Coach pay:** payout is based on attended sessions, not assigned sessions. Assigned sessions do not create payout; absent sessions are not payable.

Coach payout formula:

```text
gross_revenue = sum(session_student_count * session_fee)
net_after_rent = gross_revenue - total_rent - total_misc
coach_pool = net_after_rent * coach_pool_percent
revenue_share = coach_pool * coach_attended_sessions / total_attended_coach_sessions

if total_attended_coach_sessions == 0:
    revenue_share = 0

base_payout = max(session_floor * coach_attended_sessions, revenue_share)
```

Remaining configuration values for the architect/product owner to set:

- default `coach_pool_percent`
- default `session_floor`
- whether rent/misc are academy-wide monthly expenses or allocated by session/program
- whether credits expire or carry indefinitely

---

## Recommended Next Step

Have the AI architect turn this report into an Admin Control Plane roadmap with acceptance criteria. I recommend starting with:

1. UI professionalism cleanup.
2. Student/user/session detail and edit workflows.
3. Enrollment lifecycle audit/effective dates.
4. Payment correctness.

Those four unblock the biggest daily admin pain and reduce future data-model rework.
