# Registration/Annual Fee as a Charge Type — Requirements

Date: 2026-07-06 · Roadmap item 1 of 9 · [Index](2026-07-06-00-roadmap-index.md)

## Problem

Every competitor studied (Jackrabbit, iClassPro, Sawyer, Upper Hand, Amilia, TeamUp)
models a one-time registration/annual fee as a distinct charge type, separate from
recurring tuition. We have no such construct today. Admins who want to charge a
one-time enrollment fee, an annual membership fee, or a re-registration fee for a
returning student have no way to do it inside the app — it has to happen out of band
(cash, a separate invoice tool, or folded awkwardly into the first month's tuition,
which breaks proration math).

This is also a prerequisite for two other roadmap items: payment plans/installments
(a camp deposit is a variant of a one-time fee) and consolidated family statements
(the statement needs to show fee line items distinctly from tuition).

## Current State (codebase evidence)

- `backend/v2/contexts/billing/domain/models.py` — `LedgerInvoice` and `InvoiceLine`
  exist. `InvoiceLine` already has a generic `line_type` and `discount_kind`
  (category) field, so it can carry new line types without a schema rewrite.
- No `registration_fee` or `annual_fee` line type exists today.
- No domain concept of "charge this fee once per student per season/year" —
  enrollment billing only generates tuition lines.
- `ProrationCalculator` (session_type_proration module) handles mid-month tuition
  proration but has no concept of a fee that should *not* be prorated.

## Goals

- Let an admin define one or more fee types (e.g., "Annual Registration Fee",
  "New Student Fee") with an amount, per academy.
- Let admin attach a fee to an enrollment (new registration) or trigger it
  automatically for all active students on a recurring cadence (e.g., every
  September for an annual fee).
- Fee must appear as its own invoice line, be billed via the same Stripe Connect
  invoice/autopay path as tuition, and be refundable independently of tuition.
- Fee must NOT be prorated (unless explicitly configured otherwise) — competitors
  treat registration fees as a flat, non-prorated charge.

## Non-Goals

- No per-fee custom payment plans in this slice (that's roadmap item 4).
- No public-facing fee marketing/upsell UI in this slice — admin configuration and
  billing plumbing only.

## Requirements

### R1. Fee Type configuration (admin)
- Admin can create/edit/archive a `FeeType`: name, amount_cents, category
  (`registration` | `annual` | `other_one_time`), recurrence
  (`one_time_per_student` | `annual` | `manual`), taxable flag (future-proofing,
  no tax engine required now).
- Fee types are scoped per academy (multi-tenant — follow existing `academy_id`
  pattern used on every other aggregate).

### R2. Attaching a fee to an enrollment
- When admin approves a new registration (existing `ApproveRegistration` use case in
  `composition/admin_registration_review.py`), admin can optionally attach one or
  more configured fee types to the resulting invoice.
- Attached fee generates an `InvoiceLine` with `line_type="fee"`,
  `category=<fee category>`, `discount_kind=null` (fees are not discountable by
  default; see roadmap item 2 for whether promo codes may apply to fees).

### R3. Annual/recurring fee triggering
- A scheduled job (same pattern as existing monthly tuition invoice generation) can
  generate `annual` fee type charges for all active enrollments on a configured
  month/day, once per student per 12-month window (idempotent — do not double-charge
  if the job reruns).
- Idempotency key: `(academy_id, student_id, fee_type_id, billing_year)`.

### R4. Non-proration
- Fee lines are excluded from `ProrationCalculator` logic entirely — a fee charged
  mid-month is charged at full configured amount, not prorated by days remaining.

### R5. Refund/void behavior
- Fee lines can be voided/refunded independently of tuition lines on the same
  invoice (reuse existing `CreditLedgerEntry` refund path, scoped to a specific
  invoice line rather than the whole invoice).

### R6. Visibility
- Admin billing views (`/api/v2/admin/billing/ledger`) show fee lines distinctly
  from tuition lines (label, category badge).
- Parent-facing invoice/receipt shows the fee as its own line item with the fee
  type's configured name (e.g., "Annual Registration Fee — $50.00").

## Data Model Changes

### New `fee_types` collection
```text
fee_type_id
academy_id
name
amount_cents
category: "registration" | "annual" | "other_one_time"
recurrence: "one_time_per_student" | "annual" | "manual"
active: bool
created_at / updated_at
```

### `InvoiceLine` (extend existing)
```text
line_type: add "fee" as a valid value (alongside existing tuition/discount/etc.)
fee_type_id: string | null   # references fee_types when line_type="fee"
prorated: bool               # default false for fee lines
```

### New `fee_charges` (idempotency/audit ledger)
```text
charge_id
academy_id
student_id
fee_type_id
billing_year: int | null     # null for one_time_per_student
invoice_id
charged_at
```
Unique index: `(academy_id, student_id, fee_type_id, billing_year)`.

## Dependencies

- None. This is the foundation item other billing roadmap items build on.

## Open Decisions

1. Can promo codes/discounts ever apply to fee lines, or are fees always
   full-price? (Affects roadmap item 2's stacking-order design.)
2. Does a fee refund reduce the student's standing (e.g., un-enroll) or is it
   purely a financial adjustment?
3. Should annual fee triggering be academy-configurable (any month/day) or fixed to
   academy enrollment anniversary per student?
4. Do fee types need Stripe-side tax-category metadata now, or is that deferred
   until an actual tax engine is scoped?

## Acceptance Criteria / Test Cases

- Creating a `FeeType` and attaching it during registration approval produces an
  invoice with a distinct fee line, correctly totaled.
- A fee attached mid-month is NOT prorated (full amount charged).
- Running the annual-fee scheduler twice in the same billing year does not
  double-charge a student (idempotency key holds).
- Refunding a fee line does not affect tuition lines on the same invoice.
- Admin ledger view and parent invoice view both render the fee line with its
  configured name and category, distinct from tuition.
