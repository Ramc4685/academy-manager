# Consolidated Family Statement — Requirements

Date: 2026-07-06 · Roadmap item 3 of 9 · [Index](2026-07-06-00-roadmap-index.md)

## Problem

Competitive research found the category standard is a single rolled-up family
balance across all children, not per-child/per-enrollment invoices — Jackrabbit and
iClassPro both run family-level ledgers; Amilia goes further and auto-falls back to
another authorized family member's saved payment method if one card fails. Today,
our `LedgerInvoice` is scoped per enrollment. A parent with two children sees (and
must pay) two separate invoices instead of one consolidated balance. This is a
recurring source of admin phone calls in every competitor's review data when it's
missing (explicitly called out as a complaint against CourtReserve).

## Current State (codebase evidence)

- `backend/v2/contexts/billing/domain/models.py` — `LedgerInvoice` is generated and
  scoped per enrollment (or per student), not per family/parent.
- `Parent` in the identity/enrollment model can have multiple `ChildProfile` /
  student enrollments, but there is no `Family` or `Household` aggregate tying
  invoices together for display or payment purposes.
- Parent-facing endpoints already exist per-invoice:
  `GET /api/v2/parent/invoices`, `GET /api/v2/parent/payments`,
  `GET /api/v2/parent/credits` — these list invoices individually; there's no
  "family balance" rollup endpoint.
- `POST /api/v2/parent/checkout/start` operates against a single invoice/enrollment
  today.

## Goals

- Give parents a single "amount due" number across all their children's open
  invoices, and let them pay it in one checkout action.
- Preserve the existing per-enrollment `LedgerInvoice` as the underlying financial
  truth (billing/reporting still needs per-student granularity) — the family
  statement is a read-model/aggregation and payment-orchestration layer on top, not
  a replacement of per-enrollment invoicing.
- Support the common real-world case where one parent pays for children who may be
  enrolled under a co-parent/guardian's account too (family unit ≠ single parent
  account, in some cases).

## Non-Goals

- Not building a full "household" identity model with shared login/roles in this
  slice (that's a bigger identity change) — family grouping for billing purposes
  can be achieved via a lighter-weight `family_id` linkage without touching auth.
- Not changing per-enrollment invoice numbering or ledger semantics — this is
  additive.

## Requirements

### R1. Family grouping
- Introduce a `family_id` that groups one or more parent accounts and their
  children's enrollments for billing-rollup purposes. Default: one parent account
  = one family, auto-created. Admin (or parent, self-serve) can link a second
  parent/guardian account into the same `family_id`.

### R2. Family statement read model
- New endpoint `GET /api/v2/parent/family/statement` returns:
  - total_amount_due_cents across all open/partially-paid invoices in the family
  - per-student, per-invoice breakdown (student name, invoice number, line items,
    amount due) so the rollup is auditable, not just a black-box total
  - credit balance available (existing `CreditLedgerEntry`) applied against the
    total before display
- Admin-facing equivalent: `GET /api/v2/admin/billing/families/{family_id}/statement`.

### R3. Single-action family payment
- Extend checkout so a parent can pay the full family balance in one Stripe
  Checkout Session that internally allocates the single payment across multiple
  open invoices (reuse existing `LedgerPayment` / `PaymentAllocation` machinery —
  one Stripe charge, multiple ledger allocations).
- Partial payment against the family total must still allocate sensibly (e.g.,
  oldest invoice first, or admin-configured allocation order) and leave the
  correct remaining balance per invoice.

### R4. Autopay across a family
- Autopay (existing `AutopayConsent` / `ChargeInvoiceViaAutopay`) should be
  extendable to charge the family's consolidated balance in one PaymentIntent
  rather than one PaymentIntent per child, reducing processing fees and dunning
  complexity. (This can ship as a fast-follow if the single-action payment in R3
  ships first — flag as a phase 2 within this item if needed.)

### R5. Visibility
- Parent dashboard shows one "Family Balance" figure prominently, with a
  drill-down per child.
- Admin views (dashboard, billing ledger) can filter/search by family, not just by
  individual parent or student.

## Data Model Changes

### New `families`
```text
family_id
academy_id
primary_parent_id
member_parent_ids: [parent_id]   # co-parents/guardians linked to this family
created_at
```

### `Parent` / parent-linked records (extend)
```text
family_id: string   # backfilled = auto-generated 1:1 with parent_id if unlinked
```

### New `family_payment_allocations` (or extend existing `PaymentAllocation`)
```text
allocation_id
payment_id            # single Stripe charge
family_id
invoice_id             # one row per invoice the payment was split across
amount_allocated_cents
allocation_order: int  # audit trail of the allocation policy applied
```

## Dependencies

- Should ship after registration fees (item 1) and discount automation (item 2)
  settle their invoice-line conventions, so the statement renders fee/discount
  lines correctly per child.

## Open Decisions

1. Can two parent accounts self-link into one family without admin approval, or
   does linking require admin verification (fraud/privacy consideration — one
   parent could otherwise see another's billing by claiming a false link)?
2. Family payment allocation order on partial payment: oldest-invoice-first,
   proportional split, or admin-configurable?
3. Does autopay-across-family (R4) ship in this slice or as an immediate fast-follow?
4. How are refunds handled when they were paid via a consolidated family payment
   split across invoices — refund a specific child's invoice or must it be
   apportioned back across the original split?

## Acceptance Criteria / Test Cases

- A parent with 2 children and 2 open invoices sees one "Family Balance" figure
  equal to the sum, correctly net of any available credit.
- Paying the family balance in one checkout action correctly allocates the single
  Stripe payment across both invoices, closing whichever invoices are fully
  covered and leaving correct partial balances otherwise.
- A second guardian linked to the same family sees the same family statement.
- Admin can search/filter billing by family and see the same rollup a parent sees.
- Refunding one child's invoice does not affect the other child's invoice balance
  or payment history.
