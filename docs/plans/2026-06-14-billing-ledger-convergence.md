# Billing Ledger Convergence — Invoices, Add-on Charges & Collection

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **No phase merges before its exit gate is green.**

**Goal:** Converge student billing onto a single accounts-receivable (AR) ledger so an admin can **itemise a student's monthly bill** (tuition + ad-hoc charges like an equipment/racket purchase) and **collect it either via autopay or a sent invoice** — and retire the parallel legacy `Payment` model down to a removable projection.

**Architecture:** The **`LedgerInvoice` aggregate (billing context) becomes the single source of truth** for "what a parent owes." Invoices are itemised (`InvoiceLine`), payments are separate aggregates allocated to invoices (`PaymentAllocation`), and overpayment becomes account credit. The legacy flat `Payment` model (`billing/domain/models.py::Payment` + `mongo_payment_repo.py`) is **frozen for new writes, converted to a read projection, then marked for deletion** once historical data is backfilled. This mirrors the proven `PayoutPeriod` convergence in [2026-06-13-coach-payroll-month-first.md](2026-06-13-coach-payroll-month-first.md).

**Tech Stack:** Backend — FastAPI, MongoDB (Motor), DDD contexts (`billing`, `enrollment`), Stripe (Checkout, Subscriptions, Invoices, PaymentIntents), pytest. Frontend — Next.js App Router, React Query, TypeScript, v2 API client (`frontend/lib/api`).

---

## The Business Problem

**What the academy admin wants to do (and can't today):**

> "A student buys a racket for $40. I want to add that $40 to their June bill, next to the $60 tuition, and collect the $100 the same way I collect tuition — pull it from their autopay card, or send them an invoice to pay."

This is the single most common billing need for a service business with incidental sales (equipment, tournament fees, late fees, private-lesson top-ups, uniform). The product cannot do it. Concretely:

1. **A bill is not itemisable in practice.** The monthly charge is a single flat amount (`$60`, the session price). There is no admin path to add a second line to a student's bill. An admin's only workarounds today are wrong: collect the racket money off-platform (untracked revenue, no receipt, no reconciliation) or hand-edit a price (corrupts the tuition record).

2. **There is no "one bill, two ways to collect" flow.** Autopay (Stripe subscription) and "send an invoice / record a manual payment" are wired to *different* internal records, so an ad-hoc charge has no home that both collection paths can see.

3. **Two parallel billing systems disagree about reality.** The same concept — "what a parent owes this month" — is stored two different ways (see audit below). The student-detail "Current Payment" panel literally branches on which one exists ("Invoice balance" vs "Session price"). This is a latent data-integrity problem, not just a UX wrinkle.

**Why it matters (impact):**

- **Lost / untracked revenue.** Incidental sales happen off-book because the system can't itemise them. No audit trail, no receipt, no tax record.
- **Reconciliation risk.** Two writers (`Payment`, `LedgerPayment`) share one Mongo `payments` collection with **no discriminator field** — distinguished only by which keys happen to be present. Any query that doesn't filter perfectly can read the wrong shape. This is a bug waiting to happen *today*, independent of the feature.
- **Feature ceiling.** Discounts, fees, partial payments, credits, multi-student family invoices — every one of these is an "invoice line" problem. Without a real ledger as the source of truth, each becomes a bespoke hack.

**The good news:** the hard part is already built. [`billing/domain/ledger.py`](../../backend/v2/contexts/billing/domain/ledger.py) is a correct, immutable AR ledger (`LedgerInvoice` → `InvoiceLine`, `LedgerPayment` → `PaymentAllocation`, overpayment → `CreditLedgerEntry`) that matches the Stripe/QuickBooks/Xero standard. `InvoiceLine` already carries `line_type`, `quantity`, `unit_amount_cents`, `source_type`, `source_id` — everything an add-on charge needs. **This is a convergence + use-case problem, not a domain-redesign problem.**

---

## Current State Audit (2026-06-14)

Source: dependency audit of `backend/v2/contexts/billing`. Legacy `Payment` is **load-bearing**, not dead code.

| Surface | Backed by today |
|---|---|
| Stripe **checkout** (one-time payments) | Legacy `Payment` only |
| Stripe **payment_intent** webhooks | Legacy `Payment` only |
| **generate-monthly** job (the `$60 / 2026-06 / pending` rows) | Legacy `Payment` only |
| Admin **mark-paid / discount / undo-paid** | Legacy `Payment` only |
| Parent **/payments** history | Legacy `Payment` only |
| Stripe `invoice.paid` — **non**-session-type | Legacy `Payment` only |
| Stripe `invoice.paid` — **session-type** subscription | **Ledger** (`LedgerInvoice` + `LedgerPayment` + `PaymentAllocation`) |
| Admin **/billing/invoices** list/detail | Ledger (detail falls back to legacy) |
| Parent **/invoices** list/detail | Ledger (read-only) |

**Key risks the audit surfaced:**

1. **Shared collection, no discriminator.** `mongo_payment_repo.py` (legacy `Payment`) and `mongo_billing_ledger_repo.py` (`LedgerPayment`) both write the **`payments`** collection. They are told apart only by field presence (`ledger_idempotency_key`/`unapplied_amount_cents` vs `enrollment_id`/`stripe_checkout_session_id`). **This is the most urgent fix and is independent of the feature work.**
2. **Ledger is purpose-built but narrow.** It is only *written* on the session-type `invoice.paid` path. It is fully wired for reads (parent + admin invoice views) but is not the write-path for checkout, monthly generation, or manual ops.
3. **Asymmetric data exists now.** Some parents have a `LedgerInvoice` and **no** legacy `Payment` (session-type subscribers); most have **only** legacy `Payment` (checkout, monthly-generated, manual). Any convergence must read both until backfill completes.

---

## Domain Changes Required (vs. today's `ledger.py`)

The plan extends the existing ledger; it does not replace it. Explicit deltas:

- **`InvoiceStatus` enum** today is `open | partially_paid | paid | void`. **Add `draft` only** → `draft | open | partially_paid | paid | void`. **`sent` is NOT a financial status** (locked by review 2026-06-14 — see "Financial status vs. delivery state" below).
- **Add delivery-tracking fields** to `LedgerInvoice`, *separate from* financial status: `sent_at: datetime | None` (first delivery), `last_sent_at: datetime | None` (most recent delivery), `delivery_status: Literal["not_sent","sent","delivery_failed"] = "not_sent"`. These never affect `status`, owed amount, or balance.
- **Add `finalized_at: datetime | None`** (draft → open) for audit.
- **Add domain ops** to `ledger.py`, pure/immutable like `allocate_payment_to_invoice`:
  - `recompute_totals(invoice, lines)` → derives `subtotal_cents`/`discount_cents`/`total_cents`/`balance_due_cents` from the line set.
  - `add_line(invoice, lines, new_line)` → append + recompute; enforces edit rules.
  - `finalize(invoice)` (draft → open), `void(invoice, reason)`.
  - `record_delivery(invoice, now, outcome)` → updates `delivery_status`/`sent_at`/`last_sent_at` **only**; financial `status` is untouched.
- **Add `InvoiceLineAdded`, `InvoiceFinalized`, `InvoiceVoided`, `InvoiceDelivered` domain events.**
- **`LedgerPayment` has no `refunded_cents`.** Refunds are modelled as `CreditLedgerEntry` (existing) + optional Stripe refund — **never** by mutating a payment. See Refund & Credit Behavior.

---

## Financial status vs. delivery state (locked 2026-06-14)

**`sent` is delivery state, not money state. The two are tracked on separate axes and never mixed.** Reason: a paid invoice can still be (re-)sent; a void invoice may already have been delivered; an invoice can be sent twice. Folding "sent" into the financial enum makes those states unrepresentable and is a guaranteed future bug.

| Axis | Field(s) | Values |
|---|---|---|
| **Financial** (money state) | `status` | `draft`, `open`, `partially_paid`, `paid`, `void` |
| **Delivery** (was it emailed) | `delivery_status` + `sent_at` + `last_sent_at` | `not_sent`, `sent`, `delivery_failed` |

`SendInvoice` (path B) updates the delivery axis only. Whether the invoice is `open` or `partially_paid` is decided solely by payment allocation. The UI composes them ("`open` · sent 2026-06-12").

---

## Invoice Status Lifecycle (financial axis only)

```
            create (admin add-charge, or monthly job)
                         │
                         ▼
   ┌────────┐ finalize  ┌──────┐  payment    ┌───────────────┐ balance→0 ┌──────┐
   │ draft  ├──────────▶│ open ├────────────▶│ partially_paid├──────────▶│ paid │
   └───┬────┘           └──┬───┘  allocated   └──────┬────────┘           └──────┘
       │ discard           │                          │
       ▼                   │ void                     │ void
    ┌──────┐◀──────────────┴──────────────────────────┘
    │ void │   (paid → void NOT allowed; use refund/credit)
    └──────┘
```

(Delivery — `not_sent`/`sent`/`delivery_failed` — runs on a separate axis and is not shown here; it overlays any non-`draft` state.)

| Status | Meaning | Owed? | Parent sees it? |
|---|---|---|---|
| `draft` | Being assembled; lines mutable; not an obligation yet | No | No |
| `open` | Finalized/issued; balance owed | Yes | Yes (in portal) |
| `partially_paid` | Some payment allocated; balance > 0 | Yes (remainder) | Yes |
| `paid` | `balance_due_cents == 0` | No | Yes (receipt) |
| `void` | Cancelled/forgiven; terminal, immutable | No | Yes (marked void) |

**Transition rules:**
- `draft → open` via `finalize` (sets `finalized_at`). **Monthly-generated invoices are created directly as `open`** (no draft step) — locked 2026-06-14.
- `open → partially_paid → paid` driven only by `allocate_payment_to_invoice`.
- `draft|open|partially_paid → void` via `void` (requires reason). `paid → void` is **not** allowed (use refund/credit instead).
- `void` and `paid` are terminal for line edits.
- Delivery (`record_delivery`) may fire on any non-`draft` invoice and does **not** change `status`.

---

## Edit Rules (lines)

Lines are governed by invoice status. "Append" = add a new line and recompute; "adjustment" = append a line with negative `amount_cents` (`line_type="adjustment"`).

| Status | Add new line | Change existing line | Remove line | Notes |
|---|---|---|---|---|
| `draft` | ✅ free | ✅ free | ✅ free | Full edit; balance not yet owed |
| `open` | ✅ append only | ❌ (use adjustment) | ❌ (use adjustment) | Adding a charge raises balance; invoice stays `open`. If `delivery_status == sent`, UI flags "re-send / charge needed" |
| `partially_paid` | ✅ append only | ❌ | ❌ | Balance increases by the new line; remains `partially_paid` |
| `paid` | ❌ | ❌ | ❌ | Locked. New charges go on a **new** invoice; corrections via refund/credit |
| `void` | ❌ | ❌ | ❌ | Terminal/immutable |

Re-notify after appending a line is driven by the **delivery axis** (`delivery_status == sent`), not by the financial status — appending never changes `status`.

**Invariants (enforced in domain + asserted in tests):**
- `sum(line.amount_cents) == subtotal_cents`; `total_cents == subtotal_cents - discount_cents`; `balance_due_cents == total_cents - allocated_to_date`.
- `quantity ≥ 1`; `amount_cents == quantity * unit_amount_cents` (adjustments may be negative).
- No mutation of `paid`/`void` invoices — domain raises, never silently no-ops.
- Every line add/adjust/void emits a domain event for the audit trail.

---

## Autopay Behavior (decided)

**Admin-added items charge immediately** (user preference). Recurring tuition still rides its subscription cycle. So there are two distinct money flows:

| Charge type | Mechanism | Timing |
|---|---|---|
| Recurring tuition | Stripe **subscription** invoice | Next cycle (unchanged) |
| **Admin-added add-on** (racket, fee) on a subscriber | **Off-session `PaymentIntent`** against the saved card, for the add-on balance | **Immediate** (`ChargeInvoiceViaAutopay`) |
| Add-on on a non-subscriber | `SendInvoice` (hosted pay link) | On parent action |

Rationale: immediate charge gives the admin instant confirmation and avoids the racket silently riding a cycle weeks later (and avoids ambiguity if the subscription changes/cancels before the next cycle). **"Add to next cycle" is not built** — YAGNI, locked 2026-06-14.

**Guardrails:** off-session PI is keyed by `invoice_id` (idempotent — no double charge on retry); requires a saved default payment method; on failure the invoice's financial status is unchanged (`open`/`partially_paid`) and the admin is shown the decline reason; webhook records the `LedgerPayment` + `allocate_payment_to_invoice`.

---

## Refund & Credit Behavior (paid add-ons)

Refunds never mutate a `LedgerPayment` (no `refunded_cents` field). They are modelled as a **reversal pair**: a negative `adjustment` line is *not* used on a `paid` invoice (it's locked); instead the refund is a first-class operation producing a `CreditLedgerEntry` and, optionally, a Stripe refund.

Admin chooses one of two flavors when refunding a paid add-on:

1. **Refund to card** (money back to the parent):
   - Stripe refund on the add-on's `PaymentIntent` (full or partial) via the existing `IssueRefund` use case.
   - Record a `CreditLedgerEntry` of type representing the refund (`MANUAL_CREDIT` with `source_type="REFUND"`, `status="VOIDED"`/closed) **for audit only** — money left the system, so it is not spendable credit.
   - Invoice stays `paid`; a credit-note artifact is generated for the parent.
2. **Credit to account** (keep the money, apply to future invoices):
   - No Stripe refund. Create a spendable `CreditLedgerEntry` (`type="MANUAL_CREDIT"`, `status="APPROVED"`, `remaining_amount_cents = refund amount`).
   - Auto-applies to the next `open` invoice via the existing credit-application path.

**Rules:**
- Refund amount ≤ the add-on line's paid amount (tracked via its `PaymentAllocation`).
- Partial refunds allowed; multiple refunds on one line sum-capped at the allocated amount.
- Voiding an **unpaid** add-on (invoice still `open`/`partially_paid`) is a line adjustment, not a refund — append a negative `adjustment` line (allowed because the invoice isn't `paid`), recompute, balance drops.
- Every refund/credit emits an event and produces a parent-visible artifact. **The credit note reuses the existing invoice PDF pipeline** (locked 2026-06-14) — a distinct template is deferred unless a real need emerges.

---

## Architecture Decisions (locked)

1. **Source of truth = `LedgerInvoice`.** After Phase 3, every "what is owed" surface reads the ledger. Legacy `Payment` is a projection only.
2. **Legacy `Payment` marked for deletion, not deleted early.** Strangler-fig: freeze writes (Phase 2A) → converge reads (Phase 3) → backfill (Phase 4) → delete (Phase 5). Deletion is the **last** step, gated on zero writers + completed backfill.
3. **Storage separation is Phase 1 and ships first.** `LedgerPayment` moves to its own collection (`ledger_payments`). Recorded in `docs/adr/0011`.
4. **Add-on charges are `InvoiceLine`s.** No new "charge" concept. A racket = `line_type="equipment"`, `source_type="product"`, `source_id=<product_id>`.
5. **Invoice total is always derived from lines** via `recompute_totals`. Callers never set totals directly. Edit rules above.
6. **Two collection paths, one invoice.** `ChargeInvoiceViaAutopay` and `SendInvoice` both terminate in `allocate_payment_to_invoice()`.
7. **Autopay add-ons charge immediately** (off-session PI), **not** next cycle. No next-cycle add-on path — YAGNI (locked 2026-06-14).
8. **Refunds go through `CreditLedgerEntry` + optional Stripe refund**, never by mutating a payment.
9. **Every route tenant-scoped** (`academy_id` from JWT). **Idempotency preserved** on every Stripe/admin write (keyed by invoice/charge id, insert-first lock).
10. **`sent` is delivery state, not financial status** (locked 2026-06-14). Financial enum = `draft|open|partially_paid|paid|void`; delivery on its own axis (`delivery_status`/`sent_at`/`last_sent_at`).
11. **Monthly-generated invoices default to `open`** (no draft review step) — locked 2026-06-14.
12. **Credit notes reuse the existing invoice PDF pipeline** first (no bespoke template) — locked 2026-06-14.

---

## Production Data Audit (Phase 0 — completed 2026-06-14)

| Query | Count | Status |
|---|---|---|
| (a) Docs in `payments` total | **125** | baseline |
| (b) Docs in `payments` that are **legacy** `Payment` shape | **125** | migrate in Phase 4 |
| (c) Docs in `payments` that are **`LedgerPayment`** shape | **0** | nothing to move in Phase 1 |
| (d) `LedgerInvoice` count (`invoices` collection) | **0** | clean slate |
| (e) Parents with ledger invoice **and** legacy payment (overlap) | **0** | no dedupe risk |
| (f) Active Stripe subscriptions (autopay) | **1** | minimal autopay exposure |
| (g) Legacy `Payment` count by `status` | `succeeded: 61`, `pending: 58`, `waived: 6` | only 3 of 8 statuses used |

**Phase 0 findings (2026-06-14):**

- **100% legacy — clean slate.** All 125 payments are legacy `Payment` shape. Zero `LedgerPayment` and zero `LedgerInvoice` docs exist. No dual-write contamination and no Phase 1 storage migration needed (Phase 1 only needs to reroute future writes).
- **Phase 4 backfill scope: 125 docs.** Only 3 of 8 legacy statuses are in use: `succeeded` (61), `pending` (58), `waived` (6). No `partially_paid`, `failed`, `expired`, `refunded`, or `partially_refunded` records in prod. Backfill mapping is straightforward.
- **Backfill status mapping (prod-relevant rows only):**
  - `succeeded` → `LedgerInvoice.status=paid` + `LedgerPayment` + `PaymentAllocation`
  - `pending` → `LedgerInvoice.status=open`, no `LedgerPayment`
  - `waived` → `LedgerInvoice.status=void` (reason=`"waived"`)
- **1 active Stripe subscription.** Collection path A (`ChargeInvoiceViaAutopay`) has near-zero existing exposure; Phase 2C risk is low.
- **58 pending payments** will become `open` ledger invoices after backfill — worth reviewing for staleness before Phase 5 (legacy deletion).

---

## Phased Plan

Each phase has an **entry gate** and an **exit gate**. A phase may not merge until its exit gate is green.

### Phase 1 — Stop the bleeding: separate payment storage *(ships first, no UX change)*

- [ ] Decide + record `docs/adr/0011-billing-ledger-payment-storage.md` (separate `ledger_payments` collection).
- [ ] Point `MongoBillingLedgerRepository` `LedgerPayment` reads/writes at `ledger_payments`.
- [ ] Migration: copy `LedgerPayment`-shaped docs out of `payments` → `ledger_payments`; counts match audit (c).
- [ ] Verify: zero `LedgerPayment` docs remain in `payments`; zero legacy docs in `ledger_payments`.
- [ ] Regression: parent `/invoices`, admin `/billing/invoices`, session-type `invoice.paid` webhook still resolve.

**Exit gate:** the two payment aggregates no longer share a collection; existing billing reads pass; audit (c) fully accounted for.

### Phase 2A — Ledger invoice write-path + add-charge UI

**Entry gate:** Phase 1 green.

- [ ] Extend `ledger.py`: add `draft` to `InvoiceStatus` (NOT `sent`); add delivery fields `delivery_status`/`sent_at`/`last_sent_at` + `finalized_at`; add `recompute_totals` / `add_line` / `finalize` / `void` / `record_delivery` ops + events.
- [ ] **Product catalog (lightweight).** `Product` aggregate (`product_id`, `academy_id`, `name`, `default_unit_amount_cents`, `line_type`, `active`). Repo + admin CRUD (`/admin/billing/products`). Tenant-scoped.
- [ ] **Use case `AddInvoiceLine`** — open/draft invoice only; enforces edit rules; recomputes; idempotent; creates an `open` invoice on the fly if the student has none for the period.
- [ ] **Route the monthly job to the ledger.** `generate-monthly` creates a `LedgerInvoice` (status `open`) with one `tuition` `InvoiceLine`. Preserve proration + idempotency keys. **(This is the "freeze legacy writes" step for monthly billing.)**
- [ ] **Admin route + UI: add charge.** `POST /admin/billing/invoices/{id}/lines` (+ "create invoice for student/period"). Student-detail Billing tab "Add charge" control (product or free-text, amount, qty). Edit/remove per edit-rules table.
- [ ] Tests: recompute invariant (`sum(lines)==total`), add-line allowed in draft/open, rejected on paid/void, on-the-fly open-invoice creation, idempotent re-add.

**Exit gate:** admin can add a racket line to a June invoice; new monthly bills are `LedgerInvoice`s; legacy `generate-monthly` writer no longer runs.

### Phase 2B — Send-invoice collection (path B)

**Entry gate:** Phase 2A green.

- [ ] **Use case `SendInvoice`** — `finalize` if draft → `record_delivery` (sets `delivery_status="sent"`, `sent_at`/`last_sent_at`); **does not change financial `status`**. Generate PDF artifact (reuse existing pipeline); email hosted Checkout/pay-link. Extend, don't replace, `dues-reminders`. Re-send updates `last_sent_at` only.
- [ ] Webhook: on pay-link payment, record `LedgerPayment` (in `ledger_payments`) + `allocate_payment_to_invoice`. Idempotent by checkout/PI id.
- [ ] UI: "Send invoice" action on the Billing tab; the financial status chip is unchanged by sending; a separate **delivery badge** shows "Sent {last_sent_at}"; "re-send" appears when a charge is appended after delivery.
- [ ] Tests: send updates delivery axis only (financial status unchanged), payment→allocation→`paid`, overpayment→credit, re-send updates `last_sent_at`, send on a `partially_paid` invoice keeps `partially_paid`.

**Exit gate:** admin can send an itemised invoice and the parent can pay it; balance and financial status update only from payment, delivery tracked separately.

### Phase 2C — Autopay collection (path A, immediate charge)

**Entry gate:** Phase 2B green.

- [ ] **Use case `ChargeInvoiceViaAutopay`** — requires active subscription/saved default PM; create off-session `PaymentIntent` for the invoice balance, keyed by `invoice_id`.
- [ ] Webhook `payment_intent.succeeded` (off-session): record `LedgerPayment` + allocate; on failure surface decline reason, financial status unchanged (`open`/`partially_paid`).
- [ ] UI: "Charge autopay now" action shown only when a saved card exists; confirmation modal shows amount + card last-4.
- [ ] Tests: immediate-charge happy path, idempotent retry (no double charge), decline path, no-saved-card guard.

**Exit gate:** admin can add a racket to a subscriber's invoice and charge it to the saved card immediately, end-to-end in Stripe test mode.

### Phase 3 — Converge reads onto the ledger

**Entry gate:** Phase 2C green; all new writes are ledger.

- [ ] Admin `/payments` list → ledger (payments + allocations view).
- [ ] Parent `/payments` history → `ledger_payments`.
- [ ] Student-detail "Current Payment" panel → ledger only; drop the "Session price" legacy branch.
- [ ] Admin `/billing/invoices/{id}` detail stops falling back to legacy `Payment`.
- [ ] Unified payment-history view spanning historical legacy + new ledger during transition.

**Exit gate:** no read surface depends on the legacy `Payment` *write* shape.

### Phase 4 — Backfill historical data (mapping below)

**Entry gate:** Phase 3 green.

- [ ] Implement the mapping in **Backfill Mapping** below; idempotent + resumable; dry-run mode reporting counts.
- [ ] Reconciliation report: per-parent historical balance via legacy == via ledger; investigate every mismatch.

**Exit gate:** every historical legacy `Payment` has an equivalent ledger representation; reconciliation clean; legacy reads can be flagged off with no visible change.

### Phase 5 — Retire legacy `Payment`

**Entry gate:** Phase 4 green; legacy read flag off in prod for a full billing cycle, no incidents.

- [ ] Delete `Payment`, `MongoPaymentRepository`, legacy `generate_monthly_payments`, dead use cases, compat fallbacks.
- [ ] Final import-linter / dead-code sweep.

**Exit gate:** nothing references legacy `Payment`; CI green; one cycle observed post-removal.

---

## Backfill Mapping (legacy `Payment` → ledger)

Each legacy `Payment` doc becomes a `LedgerInvoice` + one `tuition` `InvoiceLine`, plus a `LedgerPayment` + `PaymentAllocation` when money moved. Source of truth is the **persisted Mongo doc** (which carries extra keys beyond the `Payment` pydantic model — e.g. `period`, `paid_amount_cents`, `balance_due_cents`, `invoice_number` written by `generate_monthly_payments`); confirm exact keys in the Phase 4 dry-run.

**Field mapping:**

| Target | Source (legacy `Payment` doc) |
|---|---|
| `LedgerInvoice.invoice_id` | derive `inv-from-{payment_id}` (deterministic, idempotent) |
| `LedgerInvoice.academy_id` / `parent_id` | same |
| `LedgerInvoice.student_id` / `enrollment_id` | `enrollment_id` → resolve student; copy `enrollment_id` |
| `LedgerInvoice.period` | doc `period` (fallback: month of `created_at`) |
| `LedgerInvoice.subtotal_cents` / `total_cents` | `amount_cents` |
| `LedgerInvoice.discount_cents` | doc `discount_cents` if present else `0` |
| `LedgerInvoice.balance_due_cents` | doc `balance_due_cents` if present else derived from status (below) |
| `LedgerInvoice.currency` | `currency` |
| `LedgerInvoice.due_date` | doc `due_date` if present else `created_at` date |
| `LedgerInvoice.status` | from status mapping below |
| `LedgerInvoice.delivery_status` / `sent_at` / `last_sent_at` | `"not_sent"` / `null` / `null` (per-invoice delivery wasn't tracked historically) |
| `LedgerInvoice.created_at` / `updated_at` | `created_at` / `updated_at` |
| `InvoiceLine` (single) | `line_type="tuition"`, `description="Monthly tuition {period}"`, `quantity=1`, `unit_amount_cents=amount_cents`, `amount_cents=amount_cents`, `source_type="legacy_payment"`, `source_id=payment_id` |
| `LedgerPayment` (when paid) | `payment_id="lp-from-{payment_id}"`, `amount_cents=paid_amount_cents`, `unapplied_amount_cents=0`, `status` from mapping, `payment_method`/`stripe_payment_intent_id`/`paid_at` from doc |
| `PaymentAllocation` (when paid) | `amount_cents=allocated`, links the two |
| `CreditLedgerEntry` (when refunded) | from `refunded_cents` (see status mapping) |

**Status mapping (the two-axis crux):**

| Legacy `Payment.status` | `LedgerInvoice.status` | `LedgerPayment` | Allocation | Extra |
|---|---|---|---|---|
| `pending` | `open` | none | none | balance = `amount_cents` |
| `partially_paid` | `partially_paid` | `succeeded`, `amount=paid_amount_cents` | = paid portion | balance = remainder (from doc) |
| `succeeded` | `paid` | `succeeded`, `amount=amount_cents` | = full | balance = 0 |
| `failed` | `open` | `failed` (record, **no** allocation) | none | balance = `amount_cents` |
| `expired` | `void` | none | none | reason `"checkout_expired"` |
| `waived` | `void` | none | none | reason `"waived"` (forgiven; not owed) |
| `refunded` | `paid` | `refunded`, `amount=amount_cents` | = full | `CreditLedgerEntry` source `"REFUND"`, `refunded_cents` (closed/audit) |
| `partially_refunded` | `paid` | `succeeded`, `amount=amount_cents` | = full | `CreditLedgerEntry` source `"REFUND"` for `refunded_cents` |

Notes:
- `refunded`/`partially_refunded` keep the invoice `paid` (the obligation *was* met); the refund is a separate credit-note record, since `LedgerPayment` has no refund field.
- Deterministic synthetic ids (`inv-from-*`, `lp-from-*`) make the migration idempotent and re-runnable.
- Partial amounts (`paid_amount_cents`/`balance_due_cents`) come from the persisted doc; if absent for a `partially_paid` row, the row is quarantined for manual review rather than guessed.

---

## UI Acceptance Criteria — Admin Student "Billing" Tab

The Billing tab is the primary surface. Acceptance criteria (each independently testable):

**Invoice + lines**
- [ ] Shows the current-period invoice with its **financial status chip** (`draft`/`open`/`partially_paid`/`paid`/`void`) and a **separate delivery badge** ("Sent {last_sent_at}" / "Not sent" / "Delivery failed"). The two are visually distinct and never combined into one chip.
- [ ] Lists every `InvoiceLine` with description, qty, unit price, amount, and a `line_type` label (Tuition / Equipment / Fee / Adjustment). Lines grouped by type; tuition first.
- [ ] Totals row shows **subtotal, discount, total, balance due** — and balance due always equals `total − allocated`.

**Add charge**
- [ ] "Add charge" opens a form: pick a Product (prefills price + type) **or** free-text description + amount + qty.
- [ ] Add is allowed only when status ∈ {`draft`,`open`,`partially_paid`}; disabled with tooltip on `paid`/`void`.
- [ ] After adding, the line appears, totals/balance recompute live, and (if `delivery_status == sent`) a "re-send / charge needed" banner appears.
- [ ] Editing/removing a line is allowed only in `draft`; on issued invoices the UI offers "Add adjustment" instead.

**Payments + allocations**
- [ ] Payments section lists each `LedgerPayment` (amount, method, date, status) and, per payment, the **allocations** showing which invoice/amount it was applied to.
- [ ] Overpayment shows the resulting **account credit** with its remaining balance.
- [ ] Refunds show as credit-note entries with amount + date; the invoice remains `paid`.

**Actions**
- [ ] "Send invoice" (path B) — visible on `draft`/`open`/`partially_paid`; updates the **delivery badge** only (financial status unchanged); shows confirmation; re-send updates "Sent {last_sent_at}".
- [ ] "Charge autopay now" (path A) — visible only when the parent has a saved default card; modal confirms amount + card last-4; immediate charge.
- [ ] "Record manual payment" (cash/check) — records a `LedgerPayment` + allocation.
- [ ] "Refund / credit" — on `paid` invoices/lines; admin chooses refund-to-card or credit-to-account; amount capped at allocated.
- [ ] "Void" — on non-`paid` invoices; requires reason.
- [ ] Every money action is tenant-scoped, idempotent on retry, and writes an audit entry.

---

## File Structure (indicative)

**Backend — new**
- `backend/v2/contexts/billing/domain/product.py` — `Product`
- `backend/v2/contexts/billing/application/use_cases/add_invoice_line.py` — `AddInvoiceLine`
- `backend/v2/contexts/billing/application/use_cases/collect_invoice.py` — `SendInvoice`, `ChargeInvoiceViaAutopay`
- `backend/v2/contexts/billing/application/use_cases/refund_invoice_line.py` — refund/credit
- `backend/v2/contexts/billing/infrastructure/mongo_product_repo.py`
- `backend/v2/interfaces/admin/billing_products_routes.py` — product CRUD + add-line + collect + refund
- `backend/v2/tests/...` — domain recompute/lifecycle, edit-rule guards, collection paths, backfill mapping

**Backend — modified**
- `backend/v2/contexts/billing/domain/ledger.py` — statuses, `sent_at`/`finalized_at`, ops + events
- `backend/v2/contexts/billing/infrastructure/mongo_billing_ledger_repo.py` — `ledger_payments` collection
- `backend/v2/contexts/billing/application/use_cases/admin_payment_ops.py` — monthly job → `LedgerInvoice`
- `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py` — collection-path webhooks → ledger

**Frontend — modified**
- `frontend/app/(admin)/admin/students/[studentId]/page.tsx` — Billing tab (criteria above)
- `frontend/app/(admin)/admin/payments/page.tsx` — ledger-backed
- `frontend/lib/api/...` — product, add-line, send, charge, refund clients

**Docs — new**
- `docs/adr/0011-billing-ledger-payment-storage.md`
- `docs/adr/0012-ledger-invoice-as-source-of-truth.md`

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Shared-collection read picks wrong shape mid-migration | Phase 1 separates storage **before** feature work; counts reconciled |
| Double-charging during immediate autopay | Off-session PI keyed by `invoice_id`; webhook allocation idempotent |
| Historical balance drift after backfill | Phase 4 dry-run + per-parent reconciliation; quarantine ambiguous rows; no Phase 5 until clean |
| Invoice total desyncs from line sum | Totals only via `recompute_totals`; domain test asserts `sum(lines)==total` |
| Editing an issued/paid invoice | Edit-rules table enforced in domain; adjustments not deletions on issued invoices |
| `sent` vs payment-progress conflation | Delivery is a **separate axis** (`delivery_status`/`sent_at`/`last_sent_at`); never in the financial enum |
| Refund modelled by mutating a payment | Forbidden; refunds = `CreditLedgerEntry` + optional Stripe refund |
| Parent confusion: racket on tuition bill | Lines grouped/labelled by type; itemised receipt + credit notes |

## Non-Goals

- Inventory / stock levels for products.
- Multi-currency (single-currency per academy).
- Family-level consolidated invoices (ledger supports it; out of scope here).
- "Add-on rides next subscription cycle" — **not built** (YAGNI, locked); admin-added items charge immediately.
- Changes to coach payroll (`finance` context) — separate and untouched.

## Resolved Decisions (locked 2026-06-14 review)

1. **`sent` is delivery state, not financial status.** Financial enum = `draft|open|partially_paid|paid|void`; delivery tracked via `delivery_status`/`sent_at`/`last_sent_at`. Recorded in ADR-0012.
2. **No next-cycle add-on.** Admin-added items charge immediately (off-session PI). YAGNI. Recorded in ADR-0012.
3. **Monthly-generated invoices default to `open`** (no draft review step). Recorded in ADR-0012.
4. **Credit notes reuse the existing invoice PDF pipeline** first; bespoke template deferred. Recorded in ADR-0012.

## Open Questions

_None blocking. Delivery-failure handling (retry/bounce semantics for `delivery_status="delivery_failed"`) is a Phase 2B implementation detail, not an architecture decision._
