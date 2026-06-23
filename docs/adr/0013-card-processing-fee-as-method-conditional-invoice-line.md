# ADR-0013: Card Processing Fee As A Method-Conditional Invoice Line

**Status:** Proposed
**Date:** 2026-06-22
**Deciders:** RamC (architect)
**Related:** ADR-0012 (LedgerInvoice as source of truth), ADR-0011 (separate ledger payment storage), ADR-0006/0007 (tenant scoping)
**Ticket:** Backlog / P2 — "Add credit card processing fee with ACH fee-free option"

## Context

Tuition is collected via Stripe. Card payments cost the business meaningfully more than ACH, and the business wants to **steer parents to ACH autopay** by surcharging only credit-card payments — ACH stays fee-free. The requirement is explicit and constraining:

- The fee must be **disclosed before payment**, shown as a **separate line item**, and stored **separately from tuition** (never baked in).
- It must **not** apply to ACH, **debit** cards, or **prepaid** cards (card-network/state surcharge law).
- It must be **academy-scoped configuration** (this is a SaaS product — ADR-0006/0007), **off by default**, with a **server-enforced maximum** percent.
- It must not rewrite billing architecture, change tuition pricing, or touch Plaid.

The relevant existing architecture (ADR-0012) is already a good fit: `LedgerInvoice` is the source of truth, **every charge is an `InvoiceLine` distinguished by `line_type`**, and **invoice totals are always derived from lines** via `recompute_totals`. Today only `line_type="tuition"` is emitted. Autopay (`ChargeInvoiceViaAutopay`) charges `invoice.balance_due_cents` off-session against the parent's saved card.

The genuinely hard part is **timing**: the surcharge depends on the payment instrument, but card **funding type** (credit vs debit vs prepaid) is only reliably known from Stripe **after** a `PaymentMethod` exists — i.e. *after* the parent has entered the card. Yet the fee must be disclosed *before* payment. ACH-vs-card, by contrast, is chosen up front, so the dominant ACH-steering goal is satisfiable immediately.

There is no `BillingSettings` aggregate today; per-academy billing config is greenfield.

## Decision

**The processing fee is modelled as a payment-method-conditional `InvoiceLine` with `line_type="processing_fee"`, computed at payment time from academy-scoped `BillingSettings`, applied only to confirmed credit-card payments, capped by a configured maximum. It is a separate line and a separate ledger amount; it never alters the base tuition obligation. ACH and non-surchargeable cards (debit/prepaid/unknown funding) receive no fee.**

Concretely:

1. **Domain.** Add a pure function `compute_processing_fee(subtotal_cents, settings, funding_type) -> int` and a new `line_type="processing_fee"`. The fee is derived from the **base subtotal** (tuition + add-ons − discounts), `round`-ed to cents, and **hard-capped** at `min(card_processing_fee_percent, max_card_processing_fee_percent)`. The cap is enforced in the domain, not the UI.

2. **Method gating (fail-safe).** Fee applies **only** when funding type is verified `credit`. For `ach`, `debit`, `prepaid`, **or unknown**, the fee is `0`. This directly encodes the requirement "if card type cannot be verified safely, do not surcharge."

3. **Separation of axes.** The fee line is added to the **same invoice** but is **not part of the base obligation** — it is a surcharge on the act of paying by credit card, analogous to how ADR-0012 keeps `delivery_status` orthogonal to financial status. The invoice's tuition lines and `balance_due` for the *service* are unchanged; the fee line is added at the moment a surchargeable charge is created and removed/never-created otherwise.

4. **Config.** New academy-scoped `BillingSettings`: `card_processing_fee_enabled` (default `false`), `card_processing_fee_percent` (default `3.00`), `card_processing_fee_label` (default `"Credit card processing fee"`), `ach_processing_fee_enabled` (default `false`), `ach_processing_fee_percent` (default `0`), `max_card_processing_fee_percent` (default `3.00`). Resolved from `academy_id` on the JWT — no hardcoded academy IDs.

5. **Funding-aware application per path:**
   - **Autopay (`ChargeInvoiceViaAutopay`)** — saved `PaymentMethod` ⇒ funding type is **known before charging**. Compute the exact fee, add the `processing_fee` line, charge `base + fee`. This is the primary path and ships first.
   - **Interactive checkout** — funding is unknown until card entry. Disclose the **estimated** credit-card fee up front, then **confirm funding from the PaymentIntent before capture**; if funding is debit/prepaid/unknown, charge base only and emit no fee line. (Implementation: a `PaymentElement`-based flow, or surcharge restricted to the saved-card path until that flow exists. The interactive surcharge is **not** required for the ACH-steering goal.)

6. **Ledger record.** The `LedgerPayment` and Stripe `PaymentIntent` metadata carry `base_amount_cents`, `processing_fee_cents`, `total_charged_cents`, `payment_method`, `funding_type`, `pi_id`, and (when available) `charge_id`. The invoice itemizes tuition / discounts / processing-fee / total per the requirement.

**Status is Proposed** (backlog/P2); acceptance is gated on the compliance verification in Action Items.

## Options Considered

| Option | Summary | Verdict |
|---|---|---|
| **A. Method-conditional `processing_fee` InvoiceLine, computed at pay time (chosen)** | New `line_type`, pure fee fn, funding-gated, capped, academy-scoped config | **Chosen** |
| B. Bake the fee into the tuition amount | Inflate tuition line for card payers | Rejected — requirement forbids; breaks itemization, refunds, and toggling by method; same invoice would have method-dependent tuition |
| C. Separate `Surcharge` aggregate outside the invoice | New aggregate + its own allocation/refund machinery | Rejected — re-invents allocation/refund the ledger already has (ADR-0012); loses the single-invoice view the UI needs |
| D. Let Stripe surcharge automatically | Defer fee math to Stripe | Rejected — Stripe has no native surcharging product; and ADR-0012 makes our ledger the source of truth, so the fee must live there |
| E. Add a static fee line at invoice generation | Fee fixed when the monthly invoice is created | Rejected — payment method is unknown at generation; would surcharge ACH and mis-state `balance_due` |

## Trade-off Analysis

The deciding factor is **where the fee can be computed correctly**. The surcharge is a function of *payment method*, which is not known at invoice-generation time and, for cards, not fully known until a `PaymentMethod` exists. That kills any "static line at generation" design (E) and any "bake into tuition" design (B), and it means the fee must be **applied at the payment boundary**, not the obligation boundary.

Given that, reusing the ledger's existing `InvoiceLine` + derived-totals machinery (A) is strictly cheaper and safer than a parallel surcharge aggregate (C): it inherits allocation, refund-as-credit, idempotency, and tenant scoping from ADR-0011/0012 for free, and keeps one itemized invoice for the parent and admin to read. The cost is the funding-type timing problem, which we resolve with a **fail-safe default (no surcharge unless funding is verified credit)** — the legally conservative choice, which also happens to be the simplest to reason about.

## Consequences

**Becomes easier:**
- One itemized invoice shows tuition, discounts, fee, and total — satisfies parent disclosure, admin reconciliation, and receipt/history with the existing read surfaces.
- ACH-steering ships immediately on the autopay path (method known up front) without solving the interactive-funding problem first.
- Fee is per-academy, default-off, capped server-side — SaaS-safe and reversible by config flag.

**Becomes harder:**
- Interactive (non-saved-card) checkout needs funding verification *before* capture, or a custom `PaymentElement` flow — more than a Checkout Session redirect. This is the main net-new engineering.
- Disclosure shows an *estimated* fee for interactive card entry; the captured amount must reconcile to verified funding, and the UI copy must not promise a debit/prepaid surcharge.
- Refunds must refund the fee line proportionally (as a `CreditLedgerEntry` per ADR-0012), not by mutating the payment.

**To revisit:**
- ACH surcharge fields exist in config but default off/0; revisit only if a real workflow needs them.
- If interactive card volume is high, prioritize the `PaymentElement` funding-aware flow; until then, surcharge may be limited to saved-card autopay.

## Action Items

1. [ ] **Compliance gate (blocks acceptance):** verify current Stripe surcharge support, Visa/Mastercard surcharge rules, applicable state restrictions, and debit/prepaid prohibitions. Encode findings as the funding-gating rules above.
2. [ ] Add academy-scoped `BillingSettings` (six fields, defaults as specified) + admin read/write, resolved from JWT `academy_id`.
3. [ ] Add `compute_processing_fee` (pure, capped) and `line_type="processing_fee"`; unit tests for ACH/credit/debit/prepaid/unknown and the $70 example (ACH $70.00; credit @3% → $2.10; total $72.10).
4. [ ] Wire the fee into `ChargeInvoiceViaAutopay` (saved-card funding known) with metadata `base/fee/total/funding`; keep idempotency key behavior.
5. [ ] Interactive checkout: disclose estimated fee, verify funding before capture, fail safe to no-fee; or scope surcharge to autopay until the `PaymentElement` flow lands.
6. [ ] Parent checkout + receipt UI: payment-method selector, fee line, total, disclosure copy ("ACH payments have no processing fee…").
7. [ ] Admin: show method / base / fee / total / Stripe fee / net; regression-test existing card + ACH flows remain unchanged with the feature off.
