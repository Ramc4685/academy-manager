# Role model and per-role screens — design

**Date:** 2026-09-04 · **Status:** proposed, awaiting owner sign-off · **Builds on:** PR #647 (mobile shells)

## Where the app is today
Roles: admin, coach, parent, student, owner. `owner` only means franchise scope
(cross-academy rollup); every in-academy money screen is gated on `admin`, so
today's admin is a full owner. No helper/assistant role. The sidebar's "Staff"
label has nothing behind it. Coaches are already scoped to assigned sessions and
sessions carry a replacement-coach list, which is the seed of the assistant role.

## Roles
| Role | Job | Home screen | Nav |
| --- | --- | --- | --- |
| Owner | money + governance | revenue MTD, dues, payouts due, attention queue | admin drawer, full Money group, franchise switcher |
| Admin | operations | today's sessions, then registrations / requests / dues to chase | admin drawer minus Billing Setup, Payouts, Reports (except Dues), Audit Log, money settings |
| Coach | session owner | Today | Home · Today · Sessions · Profile; calendar + messages in header |
| Assistant coach | per-session helper | Today, assigned sessions only | coach tabs; Messages and payslip hidden |
| Parent | family | one card per child (next session, attendance, latest milestone); balance banner only when due | Home · Children · Payments · Progress |

Student unchanged (read-only own progress/schedule). Platform roles unchanged.

## Permission matrix
Owner only: refunds/credits/fee waivers, pricing + fee policy, billing setup +
Stripe, coach payouts/payroll runs, revenue/session economics/reports, grant
admin, audit log, franchise rollup.

Owner + admin: sessions/rosters/waitlist, registrations/requests/pause requests,
attendance on any session, skills + level-up, coach notes, lesson plans,
messages/announcements, see any family's balance and invoices, record manual
payments, chase dues, record expenses, invite coaches/assistants/parents.
Admin's refund = "request refund" into the owner's attention queue (audited).

Coach (scoped to primary/replacement sessions): attendance, skills, notes,
lesson-plan authoring, messages to own families, own payslip.

Assistant (scoped to sessions listing them as assistant): attendance, skills,
notes only. No payroll, no lesson-plan authoring, no roster edits, no messaging.

Parent: own kids' attendance/progress/schedule, invoices/autopay/payments,
submit pause requests, waivers, receive/reply messages, sees only *shared*
coach notes.

## Industry comparison → changes
1. Owner distinct from staff admin (refunds, prices, payroll, grants behind owner tier) → add academy-level owner role, gate the owner-only rows, migration adds owner to the current admin's membership.
2. Front desk records money, manager reverses → keep manual payments with admin; refund becomes a request the owner approves; audit both sides.
3. Instructors see only their classes; assistants less → assistant role + per-session assistant list beside replacement coaches; excluded from payroll and lesson-plan authoring.
4. Owners don't need every membership → coach coverage default for owner/admin (attendance never requires a coach membership); keep parent membership only for real enrolments.
5. Parent portal child-first → reorder parent home; no new data.
6. Notes have an audience → visibility flag on coach notes; parents see shared only; assistants write but can't share.
7. Venue self check-in (#470) → not now; revisit after one-tap attendance.

## Build order
1. Owner/admin split (backend gates + data migration + trimmed admin nav + refund-request flow) — medium.
2. Assistant coach (role, per-session list, scoped surface, payroll exclusion, invite) — medium.
3. Coach attendance + skills on phones (one-tap attendance, bulk present, skills cards, note visibility) — medium.
4. Parent home kid-first — small.
5. Admin pages as cards on phones (Sessions → Students → Registrations → Payments), each verified on the 10-device matrix — large, sliced.

## Open decisions (proposed answers)
- Admin may invite other admins? → owner only.
- Assistants paid via payroll? → never; promote to coach instead.
- Coach notes default private? → yes.
