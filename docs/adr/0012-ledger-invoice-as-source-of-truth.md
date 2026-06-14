# ADR-0012: LedgerInvoice As The Billing Source Of Truth

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** RamC (architect)
**Related:** ADR-0011 (separate ledger payment storage)
**Plan:** `docs/plans/2026-06-14-billing-ledger-convergence.md`

## Context

Student billing has two parallel representations of "what a parent owes" (full audit in the convergence plan):

- **Legacy flat `Payment`** — one period, one amount, one status; no line items. Load-bearing across checkout, payment-intent webhooks, monthly generation, admin manual ops, and parent payment history.
- **AR ledger** — `LedgerInvoice` → `InvoiceLine`, `LedgerPayment` → `PaymentAllocation`, overpayment → `CreditLedgerEntry` (`billing/domain/ledger.py`). Correct and immutable, matching the Stripe/QuickBooks/Xero model, but written today only on the session-type `invoice.paid` webhook path.

The business needs itemised bills (tuition **plus** ad-hoc charges such as an equipment/racket purchase) collected either via autopay or a sent invoice. The legacy `Payment` cannot itemise; the ledger already can (`InvoiceLine` carries `line_type`/`quantity`/`unit_amount_cents`/`source_type`/`source_id`). This is a convergence + use-case problem, not a domain redesign.

A review on 2026-06-14 locked several specific decisions that this ADR records.

## Decision

**`LedgerInvoice` becomes the single source of truth for what a parent owes. All charges are `InvoiceLine`s; payments are separate aggregates allocated to invoices. Legacy `Payment` is retired to a read projection and then deleted via strangler-fig.**

### 1. Source of truth and shape

- `LedgerInvoice` is canonical. Every "what is owed" surface reads it after convergence.
- A bill is a set of `InvoiceLine`s. Tuition, equipment (racket), fees, and adjustments are all lines distinguished by `line_type`. A product catalog (lightweight per-academy `Product`) supplies reusable priced items via `source_type="product"` / `source_id`.
- **Invoice totals are always derived from lines** (`recompute_totals`); callers never set totals directly. Invariant: `sum(line.amount_cents) == subtotal_cents`, `total = subtotal − discount`, `balance_due = total − allocated`.
- Payments connect to invoices via `PaymentAllocation` (many-to-many; overpayment → `CreditLedgerEntry`). Refunds are modelled as `CreditLedgerEntry` + optional Stripe refund — **never** by mutating a payment.

### 2. Financial status vs. delivery state (locked)

- **`sent` is NOT a financial status.** The financial enum is **`draft | open | partially_paid | paid | void`**.
- Delivery is tracked on a **separate axis**: `delivery_status` (`not_sent | sent | delivery_failed`) plus `sent_at` (first send) and `last_sent_at` (most recent send).
- Rationale: delivery and money state are orthogonal. A `paid` invoice can still be (re-)sent; a `void` invoice may already have been delivered; an invoice can be sent twice. Folding "sent" into the financial enum makes those states unrepresentable and is a guaranteed future bug.
- `SendInvoice` updates the delivery axis only; financial status changes solely through payment allocation.

### 3. Collection paths (locked)

- Three admin actions, one invoice, all terminating in `allocate_payment_to_invoice`:
  - **Send invoice** — finalize (if draft) + record delivery + email a hosted pay-link.
  - **Charge autopay** — for a parent with a saved card, an **off-session `PaymentIntent` charged immediately**, keyed by `invoice_id` (idempotent).
  - **Record manual payment** — cash/check/other admin-recorded payment (no Stripe). Creates a `LedgerPayment` (`payment_method` = `cash`/`check`/etc., `recorded_by` = admin), then allocates it to the invoice via `allocate_payment_to_invoice`. Overpayment becomes account credit like any other path.
- **Admin-added add-ons charge immediately; there is no "next cycle" path (YAGNI).** Recurring tuition continues to ride its Stripe subscription cycle unchanged.

### 4. Monthly generation (locked)

- Monthly-generated invoices are created directly as **`open`** (no `draft` review step).

### 5. Credit notes (locked)

- Refund credit notes **reuse the existing invoice PDF pipeline** first. A bespoke credit-note template is deferred until a concrete need appears.

### 6. Legacy retirement (strangler-fig)

Legacy `Payment` is **not** deleted early. Sequence (plan phases): separate payment storage (ADR-0011, Phase 1) → ledger becomes the write-path + add-charge feature (Phase 2A) → send-invoice (2B) → autopay (2C) → converge reads (Phase 3) → backfill historical `Payment` → ledger (Phase 4) → **delete legacy `Payment` last** (Phase 5), gated on zero writers and a clean reconciliation.

## Enforcement

1. **Derived totals.** Totals are produced only by `recompute_totals`; a domain test asserts `sum(lines) == total` and rejects mutation of `paid`/`void` invoices.
2. **Status/delivery separation.** The `InvoiceStatus` enum excludes `sent`; delivery lives in `delivery_status`/`sent_at`/`last_sent_at`. A test asserts sending does not change financial status.
3. **Idempotency + tenant scope.** Every Stripe/admin write is keyed (invoice/charge id, insert-first lock) and tenant-scoped via `academy_id` from the JWT (ADR-0006/0007).
4. **No early deletion.** Phase 5 deletion is gated on a clean per-parent reconciliation report (legacy balance == ledger balance).

## Options Considered

### Option A: Converge onto the existing ledger; itemised invoices; retire legacy (chosen)

**Pros:**
- Reuses a correct, standard AR model already in the codebase.
- `InvoiceLine` already supports add-on charges — minimal domain change.
- Unlocks discounts, fees, partial payments, credits on one consistent model.

**Cons:**
- Multi-phase migration with a historical backfill.
- Two systems coexist during the transition.

### Option B: Extend legacy `Payment` with line items

**Pros:** No new read surfaces.

**Cons:**
- Re-invents the AR ledger that already exists, badly (no allocation, no credit model).
- Legacy `Payment` is a transactional record, not an invoice; bolting lines on conflates payment and obligation.
- Rejected.

### Option C: Make `sent` a financial status

**Pros:** One enum.

**Cons:**
- Cannot represent re-send, send-after-paid, or delivered-then-void.
- Conflates delivery with money state — a known source of billing bugs.
- Rejected (explicitly, this review).

### Option D: Add-ons ride the next subscription cycle

**Pros:** No immediate charge.

**Cons:**
- Silent weeks-later charge; ambiguous if the subscription changes/cancels first; no instant admin confirmation.
- Rejected as default (YAGNI); immediate off-session charge chosen.

## Consequences

**Becomes easier:**
- Itemised bills, add-on charges, discounts, fees, partial payments, and credits all sit on one model.
- Two clean collection paths (send / charge) into the same invoice.
- Delivery and money state evolve independently without corrupting each other.

**Becomes harder:**
- A historical backfill (legacy `Payment` → ledger) is required before deletion; ambiguous partial rows must be quarantined, not guessed.
- Read surfaces must serve a unified legacy+ledger view during the transition.
- The `ledger.py` aggregate gains `draft` status, delivery fields, and new ops/events.

**To revisit:**
- Family-level consolidated invoices (the ledger supports it; out of scope now).
- A bespoke credit-note template, if the reused invoice PDF proves insufficient.
- An opt-in "next cycle" add-on, only if a real workflow demands it.

## Action Items

1. [ ] Extend `LedgerInvoice`: add `draft` status, `delivery_status`/`sent_at`/`last_sent_at`/`finalized_at`, and ops `recompute_totals`/`add_line`/`finalize`/`void`/`record_delivery` + events.
2. [ ] Add lightweight `Product` aggregate + admin CRUD.
3. [ ] Route monthly generation to create `open` `LedgerInvoice`s.
4. [ ] Implement `AddInvoiceLine`, `SendInvoice`, `ChargeInvoiceViaAutopay`, and refund/credit use cases per the plan.
5. [ ] Converge admin/parent read surfaces onto the ledger.
6. [ ] Backfill historical `Payment` → ledger with reconciliation; then delete legacy `Payment`.
