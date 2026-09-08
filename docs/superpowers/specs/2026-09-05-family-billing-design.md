# Family billing page — design

Date: 2026-09-05. Owner decisions from the brainstorming session are recorded inline.
Companion documents: the billing surface inventory and wireframes (artifact links in the
PR description), and spec 1, `2026-09-05-payments-buckets-design.md`, whose read-model
pattern, `autopay_eligibility` helper, status vocabulary and money formatter this spec
reuses. This is the second of five specs; it covers only the Family billing page, its
read model, one new write endpoint, and the removal of the two surfaces it absorbs.

## 1. Purpose

The admin's second money job is "check a family": one parent messages, and the admin
needs the whole picture on one screen — kids and classes, what is owed, whether autopay
will run and on which card, what the system already did, and a way to fix a mistake with
a reason. Today that takes Billing Setup (registration and autopay per parent), the
student page's Billing tab (one child at a time) and the invoice dialog on Payments, and
each computes owed, paid and autopay differently.

The Family billing page is **parent-level**: one page per parent user, absorbing Billing
Setup and the student Billing tab. Facts come from one backend read model; the timeline
is built on the billing audit trail (whose route exists but no page calls) plus ledger,
attempt, dunning, lifecycle and delivery facts; every correction requires a reason and
lands in the timeline.

Out of scope: Month close, Billing Health trim, Settings Billing rules, account credit
grants, reversing a manual payment (both deferred, see §10). Nothing about how money
moves changes except the one new autopay-off endpoint in §5.

## 2. Owner decisions

| Question | Decision |
|---|---|
| Key and route | Parent user id, `/admin/families/[parentId]`. A Families list at `/admin/families` replaces Billing Setup. |
| Autopay toggle | Family-level. ON reuses the existing enable endpoint. OFF is one new endpoint that pauses every active enrollment for the parent, reason required, audited, idempotent. Open invoices are not voided; they become manual. |
| Corrections | Void unpaid · Refund Stripe-paid · One-time discount · Recurring discount · Charge card now. Account credit and Undo manual payment shown disabled ("coming later"). Every action requires a reason. |
| Timeline | Money and comms in one merged list, comms rows muted. Facts with no timestamp of their own are shown on the invoice row, never invented as events. |
| Billing Setup actions | Send invite in the header when no card is on file; Charge card now per invoice in Fix something (no parent-wide charge); Enable autopay is the toggle's ON side. Registration state is a header chip. |
| Removal | This PR: `/admin/billing-setup` redirects to `/admin/families`; the student Billing tab becomes a one-line panel linking to the family page; old specs rewritten. |

## 3. Read model and endpoint

New endpoint `GET /admin/families/{parent_id}/billing`, admin persona only (owner and
admin roles; 404 for other personas, for an unknown parent, for a user who is not a
parent, and for a parent outside the request tenant — never a 403 that confirms
existence).

Producer: `contexts/billing/infrastructure/family_billing_read_model.py`, class
`MongoFamilyBillingReadModel.build(parent_id)`. Pure shaping rules (actions, autopay
state, timeline merge) live in `contexts/billing/application/family_billing.py` so they
are unit-testable without Mongo, mirroring `collections_buckets.py`. Wiring goes in a new
`composition/families.py` attached to `app.state.admin_families` in `main.py`;
`composition/admin.py` is not touched (it sits at its 4800-line cap).

### 3.1 Queries

Fixed number of reads for one parent, batched by id sets, no per-invoice or
per-enrollment round trips:

1. `users` — the parent (name, email, phone, roles). Missing or not a parent → 404.
2. `students` where `parent_id` = parent — id, name, status.
3. `enrollments` for those students — id, session id, status, `override_price_cents`;
   `sessions` for those session ids — title, weekdays, start time, monthly price.
4. `student_billing_enrollments` for those enrollments — `autopay_enrollment_status`,
   `last_attempt_outcome`, `last_failure_code`.
5. `enrollment_discounts` active for those enrollments (recurring discount).
6. `invoices` where `parent_id` = parent, all statuses including void, sorted by period
   desc then created desc, capped at 200. Draft invoices are included and labelled draft.
7. `payment_allocations` for those invoice ids, then `ledger_payments` for the allocated
   payment ids (batch, never `find_one` — one payment can settle many invoices, PR #645).
8. `credit_applications` for those invoice ids; `account_credit_ledger` balance for the
   parent via the existing `balance_for_parent`.
9. `payment_attempts` for those invoice ids (all, sorted by `created_at`).
10. `dunning_states` for those invoice ids.
11. `billing_audit_log` for those invoice ids plus entries whose `payment_id` is in the
    allocated payment set — via a new `list_for_invoices(ids)` on
    `MongoBillingAuditLogRepository` (the per-invoice `list_for_invoice` and its route
    stay).
12. `enrollment_events` for those enrollment ids.
13. `parent_billing_customers` for the parent — card on file (`primary_payment_method_last4`,
    label, type), `billing_setup_last_invited_at`, setup status; `has_login_account` via
    the existing login-account directory for the registration chip.
14. Connected-account readiness and `billing_settings` (timezone), exactly as the
    collections read model does.

"Next charge" is computed by calling `autopay_eligibility` from spec 1 on each open
invoice with its enrollment's autopay status, the card fact and connected-account
readiness; the earliest eligible invoice's `due_date` is the next charge date. The page
never re-derives chargeability.

### 3.2 Response shape (`AdminFamilyBillingView`)

```
{
  generated_at, timezone,
  parent: { parent_id, name, email, phone },
  header: {
    balance_cents,                 # sum of balance_due_cents over open + partially_paid
    open_invoice_count,
    available_credit_cents,
    last_payment: { amount_cents, method, paid_at, invoice_ids } | null,
    autopay: {
      state: "on" | "off" | "partial" | "needs_consent",
      active_count, total_count,   # over non-cancelled enrollments
      card_last4, card_label,      # null when no card on file
      next_charge_on, next_charge_invoice_id,   # null when nothing eligible
      last_failure: { code, at } | null
    },
    registration: { state: "registered" | "invited" | "not_invited", card_on_file,
                    last_invited_at },
    enrollment_counts: { active, paused, cancelled }
  },
  students: [ { student_id, name, status,
                enrollments: [ { enrollment_id, session_id, session_title, schedule,
                                 status, monthly_price_cents, override_price_cents,
                                 autopay_status, recurring_discount: {…} | null,
                                 resume_on } ] } ],
  invoices: [ { invoice_id, invoice_number, period, student_id, student_name,
                enrollment_id, status, total_cents, paid_cents, balance_due_cents,
                due_date, created_at, paid_at, voided_at, void_reason,
                delivery: { status, last_sent_at, kind: "invoice" | "autopay_notice" },
                allocations: [ { payment_id, amount_cents, method, paid_at,
                                 stripe_payment_intent_id } ],
                credits: [ { credit_id, amount_cents } ],
                actions: [ "send" | "record_payment" | "charge_card" | "void" |
                           "refund" | "discount_once" ] } ],
  timeline: [ { at, kind: "money" | "admin" | "lifecycle" | "comms",
                code, summary, invoice_id, enrollment_id, student_name,
                actor_id, reason, amount_cents, muted } ],
  actions: [ "send_invite" | "autopay_on" | "autopay_off" | "send_invoice" |
             "record_payment" ],
  warnings: [ "attempts_unavailable" | "audit_unavailable" | "events_unavailable" ]
}
```

`paid_cents` is the allocation sum (the real figure, per the inventory), never
`total − balance`. The one exception is an invoice marked `paid` with no allocation rows
(settled before `payment_allocations` existed): it reports `total − balance` and carries
`settlement_unlinked: true`, and the row says "paid (no payment record)" instead of
showing an allocation.

### 3.3 Autopay state

Over the parent's non-cancelled enrollments' `autopay_enrollment_status`:

- `on`: every one is `active`.
- `partial`: at least one `active`, at least one not.
- `off`: none `active`, at least one `paused` (the parent consented before; the enable
  endpoint can flip `paused → active`, so the toggle is enabled).
- `needs_consent`: none `active`, none `paused` (`not_offered`, `offered`,
  `setup_started`, `disabled`). The toggle is disabled with the hint "needs parent
  consent — send invite". This mirrors the enable use case, which only flips `paused`.

`next_charge_on` is null whenever state is `off` or `needs_consent`, and also when
state is `on`/`partial` but no open invoice is eligible (no card, no connected account,
nothing open). When no card is on file while enrollments are `active`, the header shows
the same "no card on file" flag the buckets use.

### 3.4 Actions

Decided server side; the interface layer removes owner-only actions when the caller is
not the owner (using the existing owner gate), so admins never see a button the backend
would refuse. The frontend renders `actions` only.

Family-level:

| Action | Condition | Endpoint (existing unless marked) | Role |
|---|---|---|---|
| `send_invite` | no card on file | `POST /admin/billing/setup/{parent_id}/invite` | admin |
| `autopay_on` | state `off` or `partial` with a `paused` enrollment | `POST /admin/billing/setup/{parent_id}/autopay/enable` | admin |
| `autopay_off` | state `on` or `partial` | **new** `POST /admin/families/{parent_id}/autopay/pause` (§5) | admin |
| `send_invoice` | at least one open invoice | per-invoice `send` below | admin |
| `record_payment` | balance > 0 | per-invoice `record_payment` below | admin |

Per invoice:

| Action | Invoice condition | Endpoint | Role |
|---|---|---|---|
| `send` | status open or partially paid | `POST /admin/billing/invoices/{id}/send` | admin |
| `record_payment` | open or partially paid, balance > 0 | `POST /admin/billing/invoices/{id}/record-payment` with `Idempotency-Key` | admin |
| `charge_card` | open or partially paid and `autopay_eligibility` says chargeable | `POST /admin/billing/invoices/{id}/charge-autopay` | admin |
| `void` | open or partially paid **and no allocations** | `POST /admin/billing/invoices/{id}/void` | owner |
| `refund` | paid or partially paid with at least one allocation whose payment has a Stripe payment intent | `POST /admin/billing/invoices/{id}/refund` (amount ≤ Stripe-paid amount) | owner |
| `discount_once` | open, balance > 0 | `POST /admin/billing/invoices/{id}/adjustments` | owner |

Recurring discount is per enrollment, owner only, via the existing
`PUT/DELETE /admin/enrollments/{id}/tuition-discount`; it is offered from the class row,
not the invoice row. Legacy `mark-paid`, `undo-paid` and the legacy payments refund and
discount routes are not offered from this page.

## 4. Timeline

One merged list, newest first, capped at 200 entries after merge. Each source maps to
entries with a stable `code`; the summary text is composed in the pure module so the
frontend does not build sentences.

| Source | Code | Kind | Summary shape |
|---|---|---|---|
| `invoices.created_at` | `invoice_generated` | money | "Sep 2026 invoice generated · Arjun · $60" |
| `invoices.voided_at` | `invoice_voided` | money | "Sep 2026 invoice voided · enrollment paused" (`void_reason`) |
| `ledger_payments.paid_at` (one entry per payment, listing the invoices it settled) | `payment_received` | money | "$60 received · card ••42" / "· Zelle" |
| `payment_attempts` with a failure status | `charge_failed` | money | "Card declined · $120 · attempt 2" (`failure_message`) |
| `dunning_states.autopay_disabled_at` | `autopay_disabled_by_ladder` | money | "Autopay disabled after 4 failed attempts" |
| `billing_audit_log` (all actions) | `audit:<action>` | admin | "Payment recorded by admin · reason" with actor and reason |
| `enrollment_events` (`created`, `paused`, `resumed`, `cancelled`, `withdrawn`, `moved`, `promoted`, `waitlisted`) | `enrollment:<event_type>` | lifecycle | "Hannah paused by admin · resumes Oct 1" with reason |
| `invoices.last_sent_at` with `delivery_status` | `invoice_emailed` or `autopay_notice_emailed` (by the enrollment's autopay status) | comms, muted | "Sep 2026 invoice emailed" / "Autopay notice emailed" |
| `dunning_states.last_notification_at` | `failure_notice_emailed` | comms, muted | "Payment failure notice emailed" |

Receipts and dues reminders are not stored with a timestamp today, so they do not appear;
the spec does not add logging for them (follow-up in §10). Successful charge attempts are
represented by their `payment_received` entry, not duplicated.

An invoice row offers "Full audit", which calls the existing
`GET /admin/billing/invoices/{id}/audit` route and shows the raw before/after entries in a
drawer. That route is now used by a page.

## 5. New write endpoint: autopay off

`POST /admin/families/{parent_id}/autopay/pause`, admin persona (same as enable).

Body: `{ reason: str (1–500 chars, required), request_id: str (required) }`.

Behaviour, in `contexts/billing/application/use_cases/pause_family_autopay.py`:

1. Load the parent's enrollment autopay snapshots through `EnrollmentAutopayDirectory`.
2. For each snapshot with status `active`, call the guarded
   `set_autopay_enrollment_status(enrollment_id, "paused")` (the one write path; the
   domain transition table allows `active → paused`).
3. Append one `BillingAuditEntry` with action `autopay_paused` (new literal in
   `BillingAuditAction`, alongside the existing `autopay_resumed`), `actor_id` = caller,
   `reason`, `before = {enrollment_ids: [...], status: "active"}`,
   `after = {status: "paused"}`, and a deterministic `audit_id` derived from
   `request_id` so a retry cannot double-log.
4. Idempotency: keyed on `(academy_id, parent_id, request_id)` with the same
   idempotency store the enable path uses; a repeat returns the first result.
5. Returns `{ paused_count, active_count_before }`.

It does not void invoices, does not touch dunning states, and does not send email. Open
invoices become manual: the worker's `prepare_due_states` skips them because the
enrollment is no longer `active`, so on the Payments page they move from Autopay
scheduled to Awaiting payment or Past due. The read model's autopay state becomes `off`,
and the toggle's ON side (the existing enable endpoint) can flip them back.

## 6. Page

Route `/admin/families/[parentId]`, admin route group, screen meta title "Family
billing", breadcrumbs Admin · Money · Families · {parent}. Layout per wireframe 2:

- **Header**: parent name, email, phone, student count; registration chip; primary
  actions Send invoice, Record payment, More (Send invite when offered, Message → the
  composer with `?dm=`). Four tiles: Balance (with open count and available credit),
  Autopay (toggle, card, next charge or the `needs_consent` hint), Last payment
  (amount, method, date), Enrollments (active / paused).
- **Students and classes**: one row per enrollment grouped by student: class and
  schedule, status chip, monthly price (override shown when set), autopay chip,
  recurring discount, resume date when paused. Owner sees Recurring discount on the row.
- **Invoices**: one row per invoice: period, student, total, paid, balance, status chip
  (one vocabulary: draft, open, partially paid, paid, void), due date, delivery fact
  ("emailed Sep 1"), actions from `actions`. Expanding a row shows allocations (method,
  amount, date, Stripe id) and credits, and the Full audit link.
- **Timeline**: merged entries, money/admin/lifecycle rows normal, comms rows muted,
  each with date, summary, reason when present. Newest first, "Show older" past 50.
- **Fix something**: Void invoice · Refund · One-time discount · Recurring discount ·
  Charge card now, each opening a dialog that requires picking an invoice (or class) and
  a reason, plus Account credit and Undo manual payment rendered disabled with "coming
  later". Owner-only items are hidden for admins.

Every dialog: reason field required (min 1 char), confirmation copy names the invoice
and amount, error shown inline from the server message, success invalidates the family
query and the collections query so the Payments page tiles refresh.

**Families list** at `/admin/families`: the current Billing Setup table (search, status
filter, cursor paging) fed by the unchanged `GET /admin/billing/setup`, with per-row
actions removed; the row links to the family page. `/admin/billing-setup` redirects
here. Nav item "Billing Setup" becomes "Families". Bucket rows on Payments and the
student page link to the family page; the student page Billing tab becomes a single
panel: balance for the family and a link "Open family billing".

Loading: skeleton header and three skeleton sections. Error: one retry panel. Empty:
"No invoices yet" / "No activity yet" per section; a parent with no students shows the
header and an explanatory line.

## 7. Error handling

- The read model never raises for a secondary source. If attempts, audit or enrollment
  events cannot be read, the timeline is built from the remaining sources and the
  response lists the missing source in `warnings`; the page shows a muted line "Some
  history is unavailable". Primary sources (parent, students, invoices) failing is a 500.
- Actions use existing endpoints and existing error mapping (404 / 409 / 422 / 503). The
  dialog shows the server detail inline and keeps its state until the family query
  refetches.
- Owner-only actions are enforced by the backend (`require_owner`) regardless of what
  the page shows.
- The pause endpoint returns 400 with a public failure code when the parent has no
  `active` enrollment (nothing to pause), never a partial write: transitions are per
  enrollment, so a parent with three active enrollments where one write fails still
  audits the ones that changed and returns `paused_count` accordingly, with a
  `warnings` entry naming the enrollment that did not flip.

## 8. Testing

Backend:

- Unit tests for `family_billing.py`: autopay state for each combination
  (`on`/`partial`/`off`/`needs_consent`), per-invoice actions for each status and
  allocation shape (void refused with allocations, refund only with a Stripe intent,
  charge_card only when eligible), owner filtering, timeline merge order and cap,
  summary text per code, comms rows muted.
- Unit tests for `PauseFamilyAutopay`: pauses only `active` rows, audit entry written
  once, request_id replay returns the first result, nothing to pause → error code.
- Contract tests (mongomock) for `MongoFamilyBillingReadModel.build`: a family with two
  students, one paid invoice with a Stripe allocation, one open invoice, one void
  invoice with reason, a failed attempt, a dunning state that disabled autopay, an
  enrollment paused event, an invoice emailed fact; `paid_cents` equals the allocation
  sum; a payment settling two invoices produces one timeline entry; a parent with no
  students; tenant isolation (another academy's invoices for the same parent id are
  invisible); the audit batch reader returns entries for many invoices; next charge
  equals the earliest eligible due date and is null without a card.
- Interface tests: 200 for admin, 404 for coach/parent, 404 for an unknown parent,
  owner-only actions absent for an admin caller and present for the owner; the pause
  route 200 / 400 / 404 and idempotent replay; the existing invoice audit route still
  returns entries.
- Inventory manifest test updated for the new routes and the redirect.

Frontend:

- Vitest for the view helpers (actions → buttons, autopay state → toggle props, chip
  mapping through `billing-status.ts`, money through `money.ts`).
- Playwright `admin-family-billing.spec.ts` with a stubbed family: header tiles, toggle
  OFF opens a reason dialog and posts to the pause route, toggle disabled in
  `needs_consent`, invoice row expands to allocations, Void dialog requires a reason and
  posts, Refund hidden for an admin stub and visible for an owner stub, timeline shows
  muted comms rows, Full audit drawer calls the audit route, Families list links to the
  page, `/admin/billing-setup` redirects.
- Existing billing-setup and student-page billing specs rewritten to the new surfaces.
  Playwright route stubs must name `/api/v2/admin/families/**` explicitly (a `*` glob
  stops at `/`, lesson from spec 1).

## 9. Rollout

One PR. Backend read model, endpoint and pause route first, then the page, then the
redirects and removals. No migration, no data change, no env. The billing-setup routes
stay (the Families list and the toggle use them). Release note lists the removed
Billing Setup page, the moved actions, the new pause route and the changed nav item.
Rollback = revert.

## 10. Follow-ups this spec deliberately leaves

- Account credit grant endpoint (credit ledger write with reason and idempotency key),
  then enable the Account credit action.
- Ledger reversal of a manual payment, then enable Undo manual payment and retire the
  legacy `undo-paid` route.
- Receipt and dues-reminder send logs with timestamps, so they can join the timeline.
- Retiring the legacy payments refund/discount/mark-paid routes once no page calls them.
- Month close (spec 3) reads the same audit log for the autopay run summary.
