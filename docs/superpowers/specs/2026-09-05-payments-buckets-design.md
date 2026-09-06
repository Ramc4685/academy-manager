# Payments as a bucket list — design

Date: 2026-09-05. Owner decisions from the brainstorming session are recorded inline.
Companion documents: the billing surface inventory and wireframes (artifact links in the
PR description). This is the first of five specs; it covers only the Payments page and
its read model.

## 1. Purpose

The admin's most frequent money job is "work the money list": who owes, who is about to
be auto-charged, who failed, and nudge or record payments. Today that takes four pages
(Payments, Dues, Billing Health, Reports) that each compute the answer differently.

The Payments page becomes a **bucket list** for one billing period. Every family appears
in exactly one bucket, the row carries the bucket's default action, and the bucket rules
are computed once on the backend using the same eligibility checks the autopay worker
uses. The current invoice table survives as an "All invoices" tab.

Out of scope here: the Family billing page, Month close, Billing Health trim, Settings
Billing rules. Each gets its own spec. Nothing about how money moves changes.

## 2. Bucket rules

Input: one billing period `YYYY-MM` (defaults to the academy's current local month) and
the tenant from the request. A family is a parent user. A family appears in the first
bucket whose rule matches, evaluated top to bottom. Voided invoices never count anywhere.

| Order | Bucket | Rule (all conditions) | Row shows | Default action |
|---|---|---|---|---|
| 1 | **Failed autopay** | The family has an invoice in the period with `status ∈ {open, partially_paid}`, balance > 0, and a `dunning_states` row that is `active`/`processing`/`parked` with `attempt_count ≥ 1`, **or** `dunned` (autopay disabled after the ladder) | invoice total, failure reason from the latest `payment_attempts` row, `attempt N of 4`, next retry date or "no more retries" | Message, Record payment |
| 2 | **Past due** | Not autopay-eligible (see §2.1), invoice `status ∈ {open, partially_paid}`, balance > 0, `due_date < today` (academy-local) | balance, days late, months owed if more than one open invoice, last reminder date | Send reminder, Record payment |
| 3 | **Awaiting payment** | Not autopay-eligible, invoice open, balance > 0, `due_date ≥ today` | balance, "due in N days", invoice delivery status | Send reminder, Record payment |
| 4 | **Autopay scheduled** | Autopay-eligible (§2.1), invoice open, balance > 0, no failed attempt this period | amount, card last4, charge date (`due_date` at 09:00 academy-local), notice status | Skip this month |
| 5 | **Paused** | The family has at least one enrollment with `status == paused` and no row above matched | class, resume or review date, leftover balance from earlier periods | Resume |
| 6 | **Paid** | Everything else with at least one invoice in the period | amount paid, method, paid date | none; bucket collapsed by default |

Families with no invoice in the period and no paused enrollment do not appear.

### 2.1 Autopay-eligible

A family's invoice is autopay-eligible when the **worker would charge it**. The read
model must call the same predicates the worker uses, never re-implement them:

- `MongoDunningStateRepository.prepare_due_states` conditions: invoice status, balance,
  `enrollment_id` present, `student_billing_enrollments.autopay_enrollment_status == "active"`.
- `ChargeInvoiceViaAutopay` guards: a default payment method exists for the parent, and
  a ready connected account (or the platform fallback flag).

Implementation: extract those two checks into one pure function in
`contexts/billing/application/autopay_eligibility.py` (`autopay_eligibility(invoice,
enrollment, payment_method, connected_account_ready) -> Eligibility`) and have both the
worker's prepare/charge path and this read model call it. This is the only refactor of
existing worker code in this spec, and it is a pure extraction with the existing tests
kept green.

An invoice whose enrollment is autopay-active but whose parent has **no card on file**
is not eligible; it lands in Awaiting payment / Past due with a "no card on file" flag
so the admin can invite them. This matches the worker, which would fail the charge.

### 2.2 Period and dates

- Period boundaries and "today" use the academy timezone via `academy_timezone_lookup`.
- "Charge date" is the invoice `due_date`; the worker runs at 09:00 academy-local on that
  day (PR #654).
- "Days late" is `today − due_date` in academy-local days.

## 3. Read model and endpoint

New endpoint `GET /admin/payments/collections?period=YYYY-MM`, admin persona only.

Producer: `contexts/billing/infrastructure/collections_read_model.py`, class
`MongoCollectionsReadModel.build(period)`. It reads, for the tenant and period, in a
fixed number of queries (no per-family round trips):

1. `invoices` in the period with `status ≠ void`, projecting id, parent, student,
   enrollment, status, total, balance, due_date, delivery_status, last_sent_at.
2. `invoices` from earlier periods still open, per parent, for leftover balances.
3. `dunning_states` for those invoice ids.
4. Latest `payment_attempts` per invoice id (one aggregation).
5. `student_billing_enrollments` for those enrollment ids (autopay status) and the
   `enrollments` rows (status, session) for paused detection.
6. Parent default payment method and connected-account readiness (existing repos).
7. `ledger_payments` + `payment_allocations` for the period to fill the Paid bucket.
8. Reminder history: last dues reminder per parent (existing `dues_reminder` log if one
   exists; otherwise the invoice `last_sent_at`).

Response shape (`AdminCollectionsView`):

```
{
  period: "2026-09",
  generated_at, timezone,
  totals: { owed_cents, autopay_scheduled_cents, autopay_scheduled_count,
            needs_action_count, collected_cents },
  buckets: [
    { key: "failed_autopay" | "past_due" | "awaiting" | "autopay_scheduled" | "paused" | "paid",
      count, total_cents,
      families: [
        { parent_id, parent_name, parent_email,
          students: [{ student_id, name, session_title }],
          invoices: [{ invoice_id, invoice_number, period, status, total_cents,
                       balance_due_cents, due_date, delivery_status }],
          balance_cents, leftover_balance_cents,
          autopay: { status, card_last4, charge_on, notice_sent_at } | null,
          failure: { reason, attempt_count, max_attempts, next_retry_on, disabled } | null,
          pause: { resume_on, review_on, session_title } | null,
          paid: { amount_cents, method, paid_at } | null,
          last_reminder_at,
          actions: ["send_reminder" | "record_payment" | "message" | "skip_month" | "resume"]
        } ] } ]
}
```

`actions` is decided by the backend from the bucket, so the UI never invents a button the
backend would refuse.

Existing endpoints used by the row actions (no new write endpoints):

- Send reminder → `POST /admin/dues-reminders` with `parent_ids=[…]`.
- Record payment → `POST /admin/billing/invoices/{id}/record-payment` (ledger path with
  idempotency key). The legacy `mark-paid` path is not offered from this page.
- Resume → `POST /admin/enrollments/{id}/resume`.
- Message → opens the existing admin message composer prefilled to the parent.
- Skip this month → new, small: `POST /admin/billing/invoices/{id}/void` with reason
  `skipped_by_admin`, restricted to open invoices with no payments (existing void rules).
  It asks for confirmation because it is a void.

## 4. Page

Route stays `/admin/payments`. Layout per wireframe 1:

- Header: title, period picker (current month default, previous months allowed),
  "All invoices" tab, family search, "Record payment" primary button.
- Four tiles from `totals`: owed this month, autopay scheduled, needs action, collected.
- Six buckets in the fixed order above. Each has a colour stripe (red, amber, teal,
  green, grey, light grey), a count, a one-line hint of what the bucket means, and rows.
  Paid is collapsed by default; empty buckets render as a single muted line ("No failed
  autopay") rather than disappearing, so the admin learns the shape of the page.
- Row: family name (link to the student page for now; the Family billing page replaces
  the link in spec 2), student and class, amount, status chip, secondary line, actions on
  the right. Actions come from `actions`.
- "All invoices" tab: the current table, unchanged, minus the filters that duplicate a
  bucket (status "Succeeded", month filter that only filtered the page). The webhook
  card and reconciliation lookup move to Billing Health in the Billing Health spec; until
  then they stay on this tab.
- One status vocabulary: draft, open, partially paid, paid, void, with `succeeded`
  mapped to paid and `waived`/`cancelled` mapped to void at the view boundary. One money
  formatter (`formatCents` in `lib/money.ts`) replaces the six copies on the pages this
  spec touches.

Loading, error, empty: skeleton buckets while loading; on error a single retry panel;
a period with no invoices shows the tiles at zero and the "No …" bucket lines.

## 5. Dashboard tiles

The dashboard's "Payments tracked" tile is removed. It becomes three tiles fed by the
same `totals`: owed this month, autopay scheduled, needs action, each linking to the
matching bucket. "Recent payments" stays on the paid feed.

## 6. Error handling

- The read model never raises for a single bad family; a family whose data is
  inconsistent (invoice with no parent, enrollment missing) is placed in a seventh
  internal list `unclassified` returned only when `?debug=1`, and counted in a log line,
  so the page still renders.
- Actions use existing endpoints and existing error mapping; the row shows the server
  message inline and keeps its state until the list refetches.
- If the autopay eligibility helper cannot determine card or connected-account state
  (Stripe unreachable), families fall to Awaiting/Past due with `autopay.status =
  "unknown"` and a chip "autopay status unavailable", never to Autopay scheduled.

## 7. Testing

Backend:
- Unit tests for `autopay_eligibility` covering each condition, plus a test that the
  worker's `prepare_due_states` and the read model classify the same seeded invoices
  identically (the invariant that motivates the extraction).
- Contract tests (mongomock) for `MongoCollectionsReadModel.build`: one seeded family per
  bucket, a family with two students landing in one bucket by the top-most rule, a paused
  family with a leftover balance, a voided invoice excluded, a parent with autopay active
  but no card landing in Awaiting with the flag, a prior-month open invoice counted as
  leftover, tenant isolation.
- Interface test for the route (admin only, 404 for other personas, period validation).

Frontend:
- Vitest for the bucket rendering helper (actions → buttons, chip mapping, money format).
- Playwright: stub the endpoint with all six buckets and assert order, counts, tile
  values, a Record payment dialog opening from a row, Send reminder posting the right
  parent id, Paid collapsed by default, and the empty-bucket line.
- Existing Payments e2e specs updated to the tab.

## 8. Rollout

One PR. Backend read model and endpoint first (usable by the dashboard tiles alone),
then the page. No migration, no data change. Feature-flag free: the old table is still
reachable under the tab. Release note lists the removed filters and the moved tile.

## 9. Follow-ups this spec deliberately leaves

- Family billing page (spec 2) replaces the row link and hosts corrections.
- Reminder history as a first-class collection if the current log proves too thin.
- Bulk "send reminders to all past due" once the single-row action has been used for a
  month.
