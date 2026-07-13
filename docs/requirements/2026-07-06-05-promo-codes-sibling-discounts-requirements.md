# Promo Codes & Sibling/Family Discount Automation — Requirements

Date: 2026-07-06 · Roadmap item 2 of 9 · [Index](2026-07-06-00-roadmap-index.md)

## Problem

Competitive research found automated discount stacking is table stakes: Jackrabbit
and iClassPro both ship configurable sibling/multi-class discount matrices with a
documented stacking order (multi-class discount → multi-student/sibling discount →
family discount, applied in that sequence); Amilia has 8 distinct discount types
(Discount Code, Coupon, Early Bird, By Age, By Location, Question-based,
Membership-Required, Loyalty); TeamSnap has conditional fee/discount logic in its
registration builder.

We currently only have `TuitionDiscount` — a manual, per-enrollment discount an
admin applies by hand. There is no promo-code redemption flow and no automatic
sibling-count-based discount. This does not scale past a small number of families
and puts pricing errors on the admin instead of the system.

## Current State (codebase evidence)

- `backend/v2/contexts/billing/...` — `TuitionDiscount` aggregate exists with
  `SetTuitionDiscount` / `RemoveTuitionDiscount` use cases. This is manual only.
- `InvoiceLine.discount_kind` (category) field already exists, so discounts are
  already modeled as invoice line categories — this extends cleanly.
- Enrollment context supports multiple students per parent (family), but nothing
  reads "how many siblings does this parent have actively enrolled" to compute a
  discount automatically.
- No promo/coupon code concept exists anywhere in the codebase.

## Goals

- Let a parent enter a promo code at checkout that reduces their invoice total
  (percentage or flat amount), with admin-configured constraints (expiry, usage
  cap, applicable fee/tuition types).
- Automatically compute and apply a sibling/multi-child discount when a parent has
  more than one actively enrolled student, without admin intervention per family.
- Define and enforce a documented stacking order so multiple simultaneous discounts
  (promo + sibling + manual) don't compound unpredictably.

## Non-Goals

- No dynamic/AI-priced discounts.
- No affiliate/referral-code revenue-sharing logic — that's a distinct feature if
  ever pursued.
- No public marketplace-style discovery (that pattern drew explicit customer
  complaints against Sawyer's marketplace fee model in competitive research — avoid).

## Requirements

### R1. Promo Code configuration (admin)
- Admin creates a `PromoCode`: code string (unique per academy), discount type
  (`percent` | `flat_cents`), value, max_redemptions (nullable = unlimited),
  redemptions_per_family (nullable = unlimited), valid_from/valid_until,
  applies_to (`tuition` | `fee` | `all`), active flag.

### R2. Promo Code redemption (parent)
- Parent enters a code during the enrollment quote/checkout flow
  (`POST /api/v2/parent/enrollments/quote` already exists — extend it to accept
  an optional `promo_code` param and return the discounted total).
- Invalid/expired/exhausted codes return a clear rejection reason, not a generic
  error.
- A redemption is recorded (see data model) so `max_redemptions` and
  `redemptions_per_family` can be enforced atomically (no race condition allowing
  over-redemption under concurrent checkouts).

### R3. Sibling/family discount automation
- Admin configures a per-academy `SiblingDiscountSchedule`: a matrix of
  (number of actively enrolled siblings in the family) → (discount percent or flat
  amount) applied to the tuition of each additional child. Mirrors iClassPro's
  documented model.
- Computed automatically at invoice-generation time by counting the parent's other
  active enrollments — no manual per-family setup required.
- Recompute must happen when a sibling's enrollment status changes (new sibling
  enrolls, a sibling withdraws) so the discount tier stays correct going forward
  (does not retroactively adjust already-issued invoices).

### R4. Discount stacking order (must be explicit and documented)
Recommended order (matches iClassPro's documented model, adapted):
1. Multi-class discount (if a single student takes 2+ classes) — existing
   `TuitionDiscount` manual mechanism, or fold into this engine.
2. Sibling/family discount (R3), applied to the discounted amount from step 1.
3. Promo code (R2), applied last, to the amount after steps 1-2.
4. Manual admin override (`TuitionDiscount`) — always applied last and can
   override/replace automated discounts for a specific enrollment if admin needs
   an exception.
- Whatever order is chosen, it must be a named constant/config the code enforces,
  and the applied order must be visible on the invoice (each discount as a separate
  line so parents can see the math, not a single opaque "discount" total).

### R5. Visibility
- Admin ledger and parent invoice both show each discount as its own line,
  labeled with source (`Sibling Discount`, `Promo: SUMMER25`, etc.) and the order
  they were applied.

## Data Model Changes

### New `promo_codes`
```text
promo_code_id
academy_id
code: string (unique per academy, case-insensitive)
discount_type: "percent" | "flat_cents"
value
max_redemptions: int | null
redemptions_per_family: int | null
applies_to: "tuition" | "fee" | "all"
valid_from / valid_until
active: bool
```

### New `promo_code_redemptions` (idempotency/audit)
```text
redemption_id
promo_code_id
academy_id
parent_id
invoice_id
redeemed_at
```
Unique/count index: `(promo_code_id, parent_id)` to enforce
`redemptions_per_family`.

### New `sibling_discount_schedules`
```text
schedule_id
academy_id
tiers: [{ sibling_count: int, discount_type: "percent"|"flat_cents", value }]
active: bool
```

### `InvoiceLine` (extend existing)
```text
line_type: add "discount" already implied by discount_kind — formalize
  discount_source: "manual" | "sibling" | "promo_code" | "multi_class"
discount_order: int   # position in the stacking sequence, for auditability
```

## Dependencies

- Builds on the fee-type work in roadmap item 1 (shares `InvoiceLine` category
  conventions). Should ship after or alongside item 1, not before.
- Consolidated family statement (item 3) should be scoped after this, since the
  statement needs to render correctly discounted per-child lines.

## Open Decisions

1. Can a promo code and sibling discount both apply to the same invoice, or are
   they mutually exclusive per academy policy? (Default recommendation: both
   apply, per the stacking order in R4 — but confirm before building.)
2. Does the sibling discount apply to the cheapest or most expensive sibling's
   tuition? (Industry convention varies; iClassPro's docs describe discount
   eligibility ordered by prorated amount then enrollment date — decide and
   document our own rule.)
3. Should promo codes be shareable/public (e.g., embedded in marketing) or
   admin-distributed only for this first slice?
4. Do withdrawn siblings' history affect the discount tier retroactively, or only
   going forward? (Recommendation: forward-only, per R3.)

## Acceptance Criteria / Test Cases

- A family with 3 active children gets the configured 3-sibling discount tier
  automatically applied to invoices for children 2 and 3, with no admin action.
- A valid promo code reduces the invoice total by the configured amount and is
  rejected cleanly once `max_redemptions` is hit.
- Two concurrent checkouts using the same single-use promo code do not both
  succeed (redemption count enforced atomically).
- An invoice showing multi-class + sibling + promo discounts renders three
  distinct, correctly-ordered discount lines with correct final total.
- A sibling withdrawing mid-month does not retroactively alter already-issued
  invoices, only future ones.
