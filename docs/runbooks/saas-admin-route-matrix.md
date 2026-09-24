# SaaS admin route matrix

Use this matrix after completing
[blno-local-manual-test-checklist.md](blno-local-manual-test-checklist.md).
It is written for `http://blno.localhost:3000` and the admin persona.

Known gaps come from
[the admin product validation report](../requirements/2026-05-21-admin-product-validation-report.md).
Do not mark a route as product-complete when the expected workflow is listed
as a known gap.

## Route Checklist

| Route | Expected page purpose | Key data to verify | Known current gaps from product feedback | Pass/fail notes |
| --- | --- | --- | --- | --- |
| Dashboard | Give admins a tenant-scoped operational overview and triage entry point. | Active students, session activity, dues/payment attention, waivers, waitlist, and links into actionable sections. | Earlier reports called out temporary or implementation-oriented copy in some admin metrics. Verify current page does not expose architecture terms or internal IDs. | |
| Sessions | Manage class schedules, rosters, capacity, attendance context, and enrollment movement. | Session title/name, coach, day/time, location, capacity, enrolled count, waitlist count, roster state, pause/move/withdraw/remove actions. | Session edit is missing or incomplete; pause/resume/remove need effective dates, reasons, billing policy, and audit context; move/withdraw date handling must be checked carefully. | |
| Students | Let admins search, inspect, and maintain student records. | Student name, status, session enrollment, parent name/contact, attendance/payment/waiver signals, pause/move/withdraw history. | Main table previously exposed student IDs and "BFF"/loaded copy; detail/edit workflow and parent phone/full details were missing. | |
| Coaches & Parents | Manage academy users and relationships without exposing implementation identifiers. | Coach and parent names, emails, phone where available, role, linked sessions/students, active/inactive state. | Directory was read-only, exposed Mongo IDs, and lacked detail/edit pages; role management was separated from user profile. | |
| Waitlist | Track students waiting for sessions and support admission decisions. | Student, parent, requested session/program, priority/date added, status, available capacity, action history. | Verify actions are tenant-scoped and do not require raw IDs. Capture missing detail/edit or approval flow gaps found during testing. | |
| Pause requests | Review and resolve enrollment pause/resume requests with billing-safe context. | Student, parent, current session, requested effective dates, reason, billing treatment, seat policy, admin decision, audit trail. | Product report requires pause behavior settings, effective dates, reasons, billing policy, and lifecycle history; current app may not yet model all fields. | |
| Payments | Review invoices and record payment activity safely. | Invoice label, student, parent name, period, amount, discount, final amount, status, method, paid date, Stripe/manual source. | Parent/internal IDs were visible; invoice detail/PDF/receipt flow was unclear; manual partial/over-payment and v2/legacy payment ID compatibility need proof. | |
| Dues follow-up | Help admins identify overdue balances and send targeted reminders. | Parent, student, invoice count, overdue amount, due dates, previous reminder status, selected recipients. | Page previously supported only bulk send, exposed parent IDs, and lacked row selection, preview, and reminder audit. | |
| Expenses | Track academy expenses for finance and reports. | Category, amount, incurred date, note/paid-to, status, created/updated audit, totals. | Add-only behavior was verified previously; edit/delete and richer legacy field parity were missing. | |
| Coach payouts | Calculate and review coach compensation. | Coach name, month/period, payable sessions, actual/substitute coached occurrences, gross/net inputs, payout status. | Payouts were read-only or incomplete; IDs could appear; calculation needs actual coached occurrences, substitute handling, approval, paid state, and export/share flow. | |
| Coach payslip | Show a coach-specific payout statement suitable for review/export. | Coach identity, pay period, occurrence list, rates/shares, deductions, total due, approval/paid timestamps. | Payslip/export/share workflow is expected but may not be complete; verify it does not expose payout IDs in normal UI. | |
| Reports | Provide in-app dashboards first, with export as a secondary action. | Revenue, expenses, profit, dues, attendance, student/session counts, coach payout summaries, waiver compliance, filters. | Reports were mostly CSV/export-first; product asks for readable dashboards, date/session/coach filters, and export after on-screen review. | |
| Messages | Send broadcasts and direct messages to selected academy audiences. | Broadcast audience, selected sessions/parents/coaches, recipient search, message preview, delivery status, thread display. | Broadcast was global only; direct messages required recipient user IDs; audience selection, recipient picker, validation, and delivery audit were missing. | |
| Waivers | Review waiver requirements, templates, signed snapshots, and compliance by student. | Current template/version, required students, signed/pending status, signer details, accepted timestamp, signed snapshot/export/share availability. | Template management, signed-document viewing/export/share, multiple waivers, and legal retention details were missing or incomplete. | |
| Settings | Configure tenant identity, billing, notifications, roles, branding, data, and policies. | Academy display name, timezone, contact, currency, session pricing, payment gateway status, reminder/email settings, role policy, data exports. | Sidebar branding was hard-coded; timezone was free text; fees used cents labels; Stripe/email/SMS/data controls were not fully operationally connected. | |
| Audit logs | Let admins review tenant-scoped operational and security-sensitive changes. | Actor, action, target, timestamp, tenant, before/after context where appropriate, filters, export. | The product report calls for a unified audit timeline across enrollment, money, attendance, messages, waivers, settings, and support access. Verify coverage rather than assuming all events exist. | |

## Cross-Route Checks

| Check | Expected result | Pass/fail notes |
| --- | --- | --- |
| Internal IDs hidden in normal UI | Admin screens do not show Mongo IDs, Firebase UIDs, raw recipient user IDs, payout IDs, or raw student IDs except in intentional support/audit contexts. | |
| Tenant isolation | Every list and detail page shows only BLNO tenant data. The API-level proof is automated, see [Automated two-tenant isolation proof](#automated-two-tenant-isolation-proof); a manual pass here only checks what the browser renders. | |
| Persona restrictions | Coach and parent accounts cannot open admin pages by direct URL. | |
| Legacy route safety | Normal admin workflows use `/api/v2` paths in SaaS mode, and legacy `/api/*` is blocked by the SaaS guard. | |
| Unknown tenant safety | Unknown tenant host is rejected before admin data renders. | |
| Error states | Missing data, unavailable routes, and blocked workflows show user-facing states without stack traces or architecture terms. | |

## Automated two-tenant isolation proof

The two-tenant isolation proof no longer needs a manual run. It is
`backend/v2/tests/contract/test_two_tenant_isolation.py`, which runs in the
backend CI job against the job's real `mongod`.

- It boots the real v2 app in SaaS mode (only the Firebase token check is
  replaced) on a throwaway database with every migration applied, and seeds two
  academies, each with an admin, a coach, a parent, a student, a class with
  occurrences, an enrollment, an invoice with a line and a payment, an expense,
  a waitlist entry and a program. All ids and names are synthetic and distinct.
- It reads the admin, coach and parent routes from the app's router, so a new
  route is covered as soon as it is added. It needs no hand-kept list.
- For every route with a path parameter, academy A's actor for that persona
  calls it on A's host with academy B's ids. The route must not crash, must
  return none of B's data, and must leave B's stored documents unchanged.
  403/404 is the expected answer. Other outcomes are counted and reported.
- Every GET route without a path parameter is called as A, and its body must
  hold none of B's ids or names.
- For GET routes, B's own actor calls the same ids first. A 2xx there shows the
  seed created a real resource, so A's refusal comes from isolation and not
  from a missing row.
- Each actor's token is refused on the other academy's host.
- Platform routes (`/api/v2/platform/*`) are cross-tenant by design and are
  not in scope. Reviewed exceptions live in `CROSS_TENANT_ALLOWLIST` in the
  test, each with a reason. A confirmed leak goes into `KNOWN_LEAKS` as a strict
  xfail with its GitHub issue number.

Run it locally with a `mongod` on 27017 (or set `V2_MONGO_URL`):

```bash
cd backend && pytest v2/tests/contract/test_two_tenant_isolation.py -q
```

The route coverage count and the per-outcome counts appear in the warnings
summary. Frontend (browser) isolation is not covered by this test.

## Manual Notes

Use this section during a run.

| Area | Notes |
| --- | --- |
| Browser/device | |
| Local stack version or branch | |
| Seed command and timestamp | |
| Admin account used | |
| Coach account used | |
| Parent account used | |
| Blocked by missing app behavior | |
| Follow-up tickets needed | |
