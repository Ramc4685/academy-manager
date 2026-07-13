# Payment Plans / Installments (Camps & Seasonal Programs) — Requirements

Date: 2026-07-06 · Roadmap item 4 of 9 · [Index](2026-07-06-00-roadmap-index.md)

## Problem

Camp-management comparables (CampDoc, iCampPro, Campium) treat deposit + installment
payment plans as an explicit conversion lever — reducing the financial-barrier
dropoff at signup by letting a family pay a deposit now and the balance over a few
fixed installments, rather than one large upfront charge. In our own competitive
set, TeamSnap and LeagueApps both support installment autopay for registration/
season fees; Sawyer gates payment plans behind its mid-tier. We have monthly
recurring tuition autopay, but no concept of a fixed-N-installment plan with a
deposit, which is the standard shape for camps, clinics, and seasonal programs (as
distinct from month-to-month tuition).

## Current State (codebase evidence)

- `backend/v2/contexts/billing/...` — `Subscription` aggregate supports modes:
  `manual`, `monthly`, `one_time_first_month`. None of these model "N fixed
  installments totaling a known program price, with an upfront deposit."
- `AutopayConsent` and `ChargeInvoiceViaAutopay` already handle off-session charging
  against a saved payment method — the charging mechanism can be reused; what's
  missing is the installment *schedule* concept sitting above it.
- `ProrationCalculator` handles month-to-month proration, which is a different
  problem than splitting a fixed total into N installments.
- No `deposit` concept exists (relates to roadmap item 1's fee-type work — a
  deposit is effectively a non-refundable-by-default fee type variant, but with a
  distinct semantic: it's credited against the total program price, not an add-on
  charge).

## Goals

- Let an admin define a program (camp, clinic, season) with a total price, a
  required deposit amount, and an installment schedule (e.g., "$50 deposit today,
  remainder in 3 equal monthly installments").
- Charge the deposit at signup, then automatically charge each subsequent
  installment on schedule via the existing autopay charging mechanism.
- Handle a failed installment via the existing dunning machinery (roadmap item 6
  extends dunning further, but the base retry ladder already in place should apply
  here without a parallel dunning system).

## Non-Goals

- No interest-bearing/financing installment plans (e.g., partnering with a BNPL
  provider) — flat, interest-free installments only, matching category norms.
- No mid-plan renegotiation UI (changing number of installments after the plan has
  started) in this first slice — cancellation/refund of the whole plan is in
  scope, restructuring is not.

## Requirements

### R1. Payment Plan Template (admin)
- Admin defines a `PaymentPlanTemplate` attached to a program/session: total price,
  deposit amount (can be $0), number of remaining installments, installment
  frequency (`weekly` | `biweekly` | `monthly`), first-installment offset from
  signup date.

### R2. Plan instantiation at enrollment
- When a parent enrolls in a program with an attached `PaymentPlanTemplate`, a
  `PaymentPlanInstance` is created: deposit charged immediately (or at checkout
  completion), remaining installments scheduled with concrete due dates.
- Deposit uses the fee-type non-proration convention from roadmap item 1 (full
  amount, not prorated) — build after or alongside item 1.

### R3. Scheduled installment charging
- A scheduled job charges each due installment via the same off-session autopay
  path used for monthly tuition (`ChargeInvoiceViaAutopay`), generating one
  `LedgerInvoice`/`InvoiceLine` per installment for auditability.
- Idempotent per `(plan_instance_id, installment_number)` — reruns don't double
  charge.

### R4. Failed installment handling
- A failed installment enters the existing dunning ladder (`DunningState`) exactly
  like a failed monthly tuition charge — no separate/parallel failure-handling
  system. If roadmap item 6 (smart dunning) ships first, installment failures get
  those improvements automatically; if this ships first, it should still work
  correctly with the current fixed-ladder dunning.

### R5. Plan cancellation/refund
- Cancelling a payment plan (e.g., withdrawing from a camp) stops future
  installments and handles the deposit per admin-configured refund policy
  (`refundable` | `non_refundable` | `partially_refundable_before_date`).

### R6. Visibility
- Parent sees the full plan: total price, amount paid to date, remaining
  installments with dates and amounts, next charge date.
- Admin sees the same, plus which installments succeeded/failed/are pending, across
  all enrolled families in a program (for camp capacity/revenue planning).

## Data Model Changes

### New `payment_plan_templates`
```text
template_id
academy_id
program_id / session_id
total_price_cents
deposit_cents
installment_count
installment_frequency: "weekly" | "biweekly" | "monthly"
first_installment_offset_days
refund_policy: "refundable" | "non_refundable" | "partially_refundable_before_date"
refund_cutoff_date: date | null
```

### New `payment_plan_instances`
```text
instance_id
academy_id
template_id
student_id
parent_id
status: "active" | "completed" | "cancelled" | "defaulted"
deposit_invoice_id
created_at
```

### New `payment_plan_installments`
```text
installment_id
instance_id
installment_number: int
due_date
amount_cents
status: "pending" | "charged" | "failed" | "cancelled"
invoice_id: string | null
```
Unique index: `(instance_id, installment_number)`.

## Dependencies

- Builds on roadmap item 1 (fee-type / non-proration conventions for the deposit).
- Should reuse existing `AutopayConsent` / `ChargeInvoiceViaAutopay` / `DunningState`
  rather than building parallel billing machinery.

## Open Decisions

1. Can a family enroll in a payment-plan program without autopay consent (i.e.,
   pay each installment manually via a sent link), or is autopay mandatory for
   plan enrollment? (Market precedent varies; recommend requiring autopay consent
   for plans, since manual per-installment collection defeats the purpose.)
2. What happens if a plan enters `defaulted` (multiple failed installments,
   dunning exhausted) — does the student's enrollment/roster spot get pulled
   automatically, or is that always a manual admin decision?
3. Deposit refund cutoff: calendar date per template, or relative to program start
   date?
4. Should installment amounts be allowed to be uneven (e.g., a larger final
   payment) or strictly equal splits of `(total - deposit) / installment_count`?

## Acceptance Criteria / Test Cases

- Enrolling in a program with an attached plan charges the deposit immediately and
  schedules the correct number of installments at the correct dates/amounts.
- Running the installment-charging job twice for the same due date does not double
  charge (idempotency holds).
- A failed installment enters the existing dunning flow and the plan/parent see
  its failed status without a separate failure UI.
- Cancelling an active plan stops all future installments and applies the
  configured deposit refund policy correctly.
- Parent-facing plan view always sums correctly: amount paid + remaining scheduled
  installments = total price.
