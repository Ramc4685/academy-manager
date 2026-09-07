# Month close — design

Date: 2026-09-07. Owner decisions from the brainstorming session are recorded inline.
Companion documents: the billing surface inventory and wireframes (artifact links in the
PR description), and specs 1 and 2 — `2026-09-05-payments-buckets-design.md` and
`2026-09-05-family-billing-design.md` — whose read-model pattern, `autopay_eligibility`
helper, status vocabulary and money formatter this spec reuses. This is the third of
five specs; it covers the Reports page reframed as Month close, one read model, the
retirement of the Dues page, and the collapse of the several "collected this month"
computations into one.

## 1. Purpose

The admin's third money job is "month close": the two monthly runs happened — invoices
were generated and emailed on the invoice day, autopay charged on the due date — and the
owner needs to see that both ran, what they produced, and whether anything looks wrong,
before signing off on the month.

Today that answer is spread over the Reports page, the Dues page and a failed-autopay
alert card, and the numbers do not agree with each other: **six different computations
of "collected this month"** exist (§2), so the tile, the deposit slip, the QuickBooks
journal and the Payments page can each report a different figure for the same month.

Month close keeps the Reports page's route and its long-form reports, and puts the two
runs at the top. Every number on it comes from one backend read model. The failed-autopay
alert card is removed because the Payments Failed autopay bucket owns that job.

Out of scope: Billing Health trim (spec 4), Settings Billing rules (spec 5), Expenses and
Payouts (out of the redesign entirely). Nothing about how money moves changes; no
migration, no data change.

## 2. Owner decisions

| Question | Decision |
|---|---|
| Which "anything odd" checks | The four from the wireframe: invoice without enrollment · paused family still invoiced · autopay on with no card on file · autopay active on a cancelled or withdrawn enrollment. No others in this spec. |
| Dues page | Removed now. `/admin/reports/dues` and `/admin/dues` become redirects to `/admin/payments`. The WhatsApp link moves onto the Past due and Awaiting bucket rows so nothing is lost. Bulk email reminders are not re-added. |
| Exports | Keep the QuickBooks journal and the deposit slip only. The pending-payments, revenue and attendance CSVs are removed. Refunds and revenue-by-category stay as on-screen reports with no CSV. |
| Page role | Reports stays owner-only, as it is today. Month close is the same page renamed. |

## 3. One "collected"

### 3.1 What exists today

Six live computations of money received in a month, each over a different source, filter
or date field:

| # | Where | Source and filter | Nets refunds |
|---|---|---|---|
| A | `make_reports_kpis` → `dues_collected_mtd_cents` | `ledger_payments`, `status ∈ {succeeded, paid}`, **`created_at`** in month | yes |
| B | `make_reports_dashboard` → `cash_collected_cents` | `ledger_payments`, `status ∈ {succeeded, paid, partially_refunded, refunded}`, **effective date** (`paid_at`, else `created_at`) in month, plus legacy `payments` deduped by provider key | yes |
| C | Payments Collections tile → `totals.collected_cents` | sum of `payment_allocations` against **this period's invoices**, no date filter | no |
| D | Deposit slip → `total_cents` | `ledger_payments`, success statuses, effective date in month, grouped by day and method | **no, gross by design** |
| E | Revenue by category → `total_allocated_cents` | `payment_allocations` with `created_at` in month, prorated across invoice lines | no |
| F | `/admin/finance/revenue` `by_month` (dashboard tile and trend chart) | ledger aggregation merged with legacy `payments`, duplicates subtracted per month | yes |

A is dead weight: `GET /admin/reports/kpis` has no frontend caller. C answers a different
question (money against this month's invoices, whenever it arrived). D is deliberately
gross because a deposit slip must match the bank. E is income by category, not cash.

### 3.2 What this spec does

One reader becomes the definition of **cash received in a period**:

`contexts/billing/infrastructure/cash_received.py`

```python
@dataclass(frozen=True)
class CashReceivedRow:
    payment_id: str
    at: datetime          # effective date, academy-local date derived by the caller
    method: str
    gross_cents: int
    refunded_cents: int
    source: Literal["ledger", "legacy"]

@dataclass(frozen=True)
class CashReceived:
    gross_cents: int
    refunded_cents: int
    net_cents: int        # gross - refunded, floored at 0 per payment
    rows: tuple[CashReceivedRow, ...]

async def cash_received_in_period(
    db, *, academy_id: str, start: datetime, end: datetime
) -> CashReceived
```

It is B's logic, extracted verbatim: the same `ledger_payment_effective_window_query`,
the same success statuses, the same `payment_revenue_net_cents` per row, the same legacy
`payments` candidate query with provider-key de-duplication against invoice and ledger
keys. Extraction only — no behaviour change, and B's existing tests stay green as the
proof.

Callers after this spec:

- **Month close** `money.collected_cents` = `net_cents`.
- **Reports dashboard** `cash_collected_cents` and `profit_and_loss.revenue_cents` call
  it instead of inlining the two passes.

**The deposit slip and the QuickBooks journal are deliberately left alone.** They look
like they should share this reader, and they must not, for two reasons found while
specifying:

- The slip's gross is `amount_cents` per ledger row, while the cash reader's gross half
  is `paid_amount_cents` / `amount_received_cents` when present. Those differ on rows
  where Stripe reported a settled amount separate from the requested one.
- The slip reads **ledger payments only**; the cash reader also folds in de-duplicated
  legacy `payments` rows.

Pointing the slip at the reader would therefore change both the per-row amount and the
row membership of a document whose whole purpose is to match a bank deposit, and it would
flow straight into the QuickBooks `Undeposited Funds` debit. That is a real change to
book-keeping output and is not something this spec should make as a side effect of a
refactor. Both keep their current computation; §11 carries the follow-up. This is also
what keeps the "existing tests pass unchanged" claim honest: the extraction is scoped to
the dashboard, and the financial-report tests are untouched because the reports are.

Deleted: `make_reports_kpis`, `GET /admin/reports/kpis`, `getAdminReportKpis`, and their
tests. Nothing calls them.

Not changed: E (revenue by category) stays allocation-based, because income by category
is genuinely a different fact from cash received; and C stays as it is but is
**relabelled** on the Payments page from "Collected" to "Paid toward this month's
invoices", so it no longer claims to be the same number. This relabel is the only change
this spec makes to the Payments page besides the WhatsApp action in §7.

## 4. Read model and endpoint

New endpoint `GET /admin/reports/month-close?period=YYYY-MM`, **owner only** — added to
`OWNER_ONLY_ROUTE_PATHS` in `interfaces/admin/owner_gate.py`, which the structural
owner-gate test verifies in both directions. A non-owner persona gets 404, never 403.
`period` validates as `YYYY-MM` (422 otherwise) and defaults to the academy's current
local month.

Producer: `contexts/billing/infrastructure/month_close_read_model.py`, class
`MongoMonthCloseReadModel.build(period)`. Pure shaping rules live in
`contexts/billing/application/month_close.py` so they are unit-testable without Mongo,
mirroring `collections_buckets.py` and `family_billing.py`. Wiring goes in a new
`composition/month_close.py` attached to `app.state.admin_month_close` in `main.py`.
`composition/admin.py` is not touched: it sits at 4751 lines against a 4800 budget.

Constructor mirrors the collections read model exactly:

```python
def __init__(self, db, *, academy_timezone, connected_accounts, billing_settings,
             customers, clock = lambda: datetime.now(UTC)) -> None
async def build(self, period: str | None = None) -> dict[str, Any]
```

`academy_id` comes from `current_academy_id()` at build time; the timezone from
`academy_timezone_lookup`, falling back to UTC with a logged warning; `today` and the
default period are academy-local.

### 4.1 Queries

Batched by id set, fixed count, no per-family round trips:

1. `invoices` for the period, **all statuses including void and draft**, projecting
   status, total, balance, parent, student, enrollment, period, due_date, created_at,
   delivery_status, last_sent_at, voided_at, void_reason.
2. `cash_received_in_period` (§3.2) for the period bounds.
3. `payment_attempts` for those invoice ids, excluding non-charge kinds via
   `exclude_non_charge_attempts`, projecting invoice, status, created_at, failure code.
4. `dunning_states` for those invoice ids: status, attempt_count, next/last attempt,
   `autopay_disable_status`.
5. `student_billing_enrollments` for the invoices' enrollment ids:
   `autopay_enrollment_status`.
6. `enrollments` for those ids: status (`active`, `paused`, `cancelled`, `withdrawn`).
7. `enrollment_billing_deferrals` for those enrollment ids (paused-month evidence).
8. `parent_billing_customers` for the invoices' parent ids: card on file via the
   existing `display_payment_method`.
9. `users` for the parent ids: display name, for the odd-list links.
10. `enrollment_discounts` and `invoice_lines` for the tuition-discount card, exactly as
    `GET /admin/finance/tuition-discounts` computes them today (the existing use case is
    called, not re-implemented).
11. Connected-account readiness and `billing_settings`, as the collections read model
    does, for `autopay_eligibility`.

### 4.2 Response shape (`AdminMonthCloseView`)

```
{
  generated_at, timezone, period,
  invoices: {
    generated, emailed, autopay_notices, not_sent,
    voided, voided_cents, void_reasons: [ { reason, count } ]
  },
  money: {
    billed_cents, collected_cents, outstanding_cents, collection_rate
  },
  autopay_run: {
    charge_on,                       # the period's due date, academy-local
    has_run,                         # today >= charge_on
    scheduled: { count, cents },
    succeeded: { count, cents },
    failed:    { count, cents },
    pending:   { count, cents }
  },
  odd: [ { code, label, count,
           items: [ { kind: "family" | "invoice", id, label, href } ] } ],
  tuition_discounts: { gross_cents, discount_cents, net_cents,
                       by_category: [ { category, amount_cents } ] },
  warnings: [ "attempts_unavailable" | "dunning_unavailable" |
              "discounts_unavailable" ]
}
```

### 4.3 How each number is defined

**Invoices.** `generated` counts invoices whose `period` is the period and whose status
is not `draft`. `emailed` and `autopay_notices` split the invoices with
`delivery_status == "sent"`; `not_sent` counts `not_sent` and `delivery_failed` together.

> The kind of email sent is **not persisted**. `record_delivery` writes the same
> `delivery_status` / `last_sent_at` for an invoice email and for an autopay notice, so
> the split is re-derived from the enrollment's *current* `autopay_enrollment_status`,
> exactly as the family timeline does. An enrollment whose autopay changed after the
> send moves between the two counts. The counts are labelled "invoices emailed" and
> "autopay notices" and their sum is always the true sent count, which is the number
> that matters for close. Persisting the message kind is a follow-up (§10).

`voided` counts invoices for the period with status `void`, `voided_cents` their totals,
and `void_reasons` groups by `void_reason` so "5 voided" is always explainable.

**Money.** `billed_cents` and `outstanding_cents` keep the dashboard's existing
definitions (`invoice_paid_cents + invoice_outstanding_cents` over non-void invoices;
`invoice_outstanding_cents`). `collected_cents` is §3.2. `collection_rate` is
`min(collected / billed, 1)` when `billed > 0`, else `null` — rendered as "—", never as
0%, so an empty month does not read as a total failure.

**Autopay run.** `charge_on` is the earliest `due_date` among the period's invoices. The
generator normally sets one due date for the whole run from `invoice_due_days`, but a
late-added enrollment gets a later one; when the dates differ the box shows the earliest
and appends "and later", while the tallies always span every autopay-active invoice in
the period regardless of its due date. The four tallies partition those invoices:

- `failed` uses the same ladder predicate as the Failed autopay bucket
  (`collections_buckets`): status `dunned`, or `active`/`processing` with
  `attempt_count >= 1`. Its tile links to `/admin/payments` (Failed autopay bucket).
- `succeeded` is an invoice with a succeeded charge attempt in the period.
- `pending` is autopay-eligible with no attempt yet — non-zero only before the run.
- `scheduled` is the sum of the three, i.e. what the worker had to do.

Before `charge_on`, `has_run` is false and the box says "runs on {date}" with the
scheduled figure only.

**Odd.** Each check yields a count and up to 20 linked items; the count is the true
count, and the list says "showing 20 of N" when truncated.

| Code | Rule | Item link |
|---|---|---|
| `invoice_without_enrollment` | Period invoice, status not void, `enrollment_id` missing or not found | invoice |
| `paused_family_invoiced` | Period invoice, status not void, balance > 0, enrollment status `paused` | family |
| `autopay_no_card` | Enrollment `autopay_enrollment_status == active` with a period invoice, parent has no card on file | family |
| `autopay_on_dead_enrollment` | `autopay_enrollment_status == active`, enrollment status `cancelled` or `withdrawn` | family |

All four are computed in the pure module from the fact sets already loaded — no extra
queries. A check with count 0 still renders, showing a zero, so the owner learns the
shape of the box.

## 5. Page

Route stays `/admin/reports`. Title, nav item and breadcrumb become **Month close**.
Layout per wireframe 3:

- Header: title, period picker (current month default, earlier months allowed), and two
  export buttons — QuickBooks and Deposit slip.
- Six tiles: invoices generated · emailed and autopay notices · voided · billed ·
  collected with the rate · outstanding.
- Two boxes side by side: **Autopay run** (charge date, scheduled, succeeded, failed
  linking to the Payments Failed bucket) and **Anything odd** (four rows, each a count
  and, when non-zero, an expandable list of links).
- **Tuition discounts**, moved from the Dues page unchanged: gross, discounts, net and
  the by-category table, driven by the same period picker rather than its own URL param.
- Then the existing long-form sections in their current order: profit and loss, AR aging
  with its drill-down, expenses, coach payroll, projected income, revenue trend, and the
  funnel / attendance / coach-utilisation analytics panels.
- Financial report links (refunds, revenue by category, deposit slip, session economics)
  stay as link cards.

Removed from the page:

- The **failed-autopay alert card** with its Retry charge and Notify parent buttons. The
  Failed autopay bucket owns this, with the audited charge path from PR #666. This also
  removes the third copy of the retry mutation.
- The **recent payments feed**. The dashboard already carries it on the paid feed, and
  its removal takes out `paymentFeedQuery.data.payments.length` — the unguarded
  dereference that is currently crashing the nightly WebKit run on `main`.
- The **pending-payments, revenue and attendance CSV exports** and their inline preview.
  `_EXPORT_REPORTS` keeps `refunds`, `revenue-by-category`, `deposit-slip` and
  `quickbooks`.

The page uses `formatCents` from `lib/money.ts` and `billing-status.ts` for chips,
replacing the five local formatters defined in the page file.

## 6. Dues removal

- `/admin/reports/dues` and `/admin/dues` become redirect stubs to `/admin/payments`.
  Both `page.tsx` files stay, so the route-manifest equality test still passes; their
  manifest entries are rewritten to a single "redirects to Payments" workflow.
- The dashboard's "Overdue dues" attention card keeps its data source and changes its
  `href` to `/admin/payments`.
- `GET /admin/dues-followup` and the frontend `listDuesFollowup` are deleted.
  **The composition closure `list_dues_followup` stays**: the dashboard's attention-card
  builder reads it directly, and it is where the WhatsApp deep link and reminder text are
  composed, which §7 reuses. Only the HTTP route and its client go.
  `POST /admin/dues-reminders` stays: the buckets' Send reminder action uses it.
- The tuition-discount card moves to Month close (§5). `GET /admin/finance/tuition-discounts`
  is unchanged and now has one caller.
- Nav loses the Dues item; `OWNER_ONLY_ROUTE_EXCEPTIONS` loses `/admin/reports/dues`,
  since the redirect target is admin-visible anyway.

## 7. WhatsApp on the buckets

The Dues page was the only surface with a WhatsApp deep link. The collections read model
already loads the parent `users` documents, so it gains `phone`, and the view gains
`whatsapp_url` on rows in the **Past due** and **Awaiting payment** buckets only, built
by the existing `whatsapp_deep_link` with the existing `dues_reminder_text` — the same
message the Dues page sent, with the parent payments link and academy name resolved once
per build, as the dues closure did.

`FamilyAction` gains `whatsapp`; the row renders it as a link, not a mutation. A family
with no phone number simply does not get the action. This is the only change to spec 1's
bucket contract, and the rule that a row action targets `action_invoice_id` is unaffected
because the WhatsApp message is family-level.

## 8. Error handling

- Primary sources (invoices, cash received) failing is a 500. Secondary sources
  (attempts, dunning, discounts) degrade through the same `_secondary` pattern the family
  read model uses: the section renders what it can and the response lists the missing
  source in `warnings`, which the page shows as one muted line.
- If connected-account or card state cannot be determined, `autopay_no_card` is
  suppressed rather than guessed, and a warning is emitted. The read model never reports
  an odd count it cannot stand behind.
- A period with no invoices returns zeros, a null collection rate and an empty odd list
  with all four checks at 0.

## 9. Testing

Backend:

- Unit tests for `month_close.py`: each of the four odd checks (positive and negative
  case), the autopay-run partition before and after the charge date, void reason
  grouping, the emailed / notice split from autopay status, collection rate null on zero
  billed, truncation to 20 items with a true count.
- Unit tests for `cash_received_in_period`: gross vs net, a refunded payment, a legacy
  row deduped against a ledger row by provider key, a payment with `paid_at` null falling
  back to `created_at`, and a test asserting the dashboard's `cash_collected_cents` is
  unchanged by the extraction against a seeded fixture.
- Contract tests (mongomock) for `MongoMonthCloseReadModel.build`: one seeded month
  covering every tile, a voided invoice with a reason, a paused enrollment still
  invoiced, an autopay-active enrollment with no card, an autopay-active cancelled
  enrollment, an invoice with no enrollment, tenant isolation, and a degraded run with
  `payment_attempts` unavailable producing a warning rather than an error.
- Interface tests: 200 for owner, 404 for admin, coach and parent, 422 on a bad period,
  503 when unwired; `GET /admin/reports/kpis` and `GET /admin/dues-followup` gone;
  the structural owner-gate test covering the new route.
- Deposit slip and QuickBooks tests re-run unchanged as the extraction's proof.
- Inventory manifest: the two dues entries rewritten to the redirect workflow, the
  `/admin/reports` entry's removed buttons and modals dropped, acceptance strings kept at
  or above the workflow and risk-edge counts. Route count stays 91.

Frontend:

- Node test for the month-close view helper (tiles, odd rows, run box states, rate "—").
- Playwright `admin-month-close.spec.ts` with a stubbed payload: tiles, the run box
  before and after the charge date, an odd row expanding to links, the failed tile
  linking to Payments, the tuition-discount card following the period picker, QuickBooks
  and Deposit slip exports firing, and no console errors. Route stubs name
  `/api/v2/admin/reports/month-close` explicitly (a `*` glob stops at `/`, lesson from
  spec 1).
- Updated: `admin-shell.spec.ts` (nav label, removed Dues item), the route-matrix spec
  (dues redirects), `tuition-discounts.spec.ts` (card now on Month close),
  `admin-payments-buckets.spec.ts` (WhatsApp action, relabelled tile), and
  `screen-meta.test.ts`.

## 10. Rollout

One PR. Backend first: the cash-received extraction with existing tests green, then the
read model, the route and the deletions; then the page; then the redirects and the
manifest. No migration, no data change, no env, no feature flag. Rollback is a revert.

The release note lists: Reports renamed to Month close, the Dues page removed with
WhatsApp moved to the buckets, the removed CSV exports, the removed failed-autopay card,
and the deleted `kpis` and `dues-followup` routes.

## 11. Follow-ups this spec deliberately leaves

- Persist the sent message kind on the invoice (`delivery_kind`), so emailed vs autopay
  notice is a stored fact rather than a re-derivation here and in the family timeline.
- Persist the generation and send run results (`SendGeneratedInvoicesResult` counts are
  returned per run and thrown away), so month close can show what the job itself
  believed it did, and disagreement with the derived counts becomes visible.
- Bulk "send reminders to every past due family" on the Payments page, once the
  single-row action has been used for a month.
- Retire the `payment_allocations`-based Collections tile in favour of a cash figure, if
  the relabel proves confusing rather than clarifying.
- Reconcile the deposit slip and the QuickBooks journal with the cash reader (§3.2). They
  differ in per-row amount and in whether legacy payments count, so unifying them changes
  book-keeping output and needs its own PR and its own sign-off.
- Billing Health trim (spec 4) and Settings Billing rules (spec 5).
