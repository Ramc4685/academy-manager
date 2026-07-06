# Smart Decline-Aware Dunning & Separate ACH-Return Handling — Requirements

Date: 2026-07-06 · Roadmap item 6 of 9 · [Index](2026-07-06-00-roadmap-index.md)

## Problem

Industry dunning literature (referenced in the 2026-07-05 billing deep-dive) shows
decline-code-aware "smart" retry timing recovers 2-4x more failed payments than a
fixed retry schedule, because different decline reasons (insufficient funds vs.
expired card vs. do-not-honor) have different optimal re-attempt windows. Our
current dunning is a single fixed ladder (0/3/5/7 days) applied uniformly regardless
of decline reason, and — more importantly — it does not distinguish an ACH return
(bank-side rejection, different codes, different timelines, potential NSF fee
implications) from a card decline. No competitor studied does this well either
(Amilia's dunning is fully manual; LeagueApps has no automated retry at all), so
this is a genuine differentiation opportunity, not just a defensive fix.

## Current State (codebase evidence)

- `backend/v2/contexts/billing/...` — `DunningState` aggregate exists: status
  (`active`/`processing`/`resolved`/`dunned`/`suppressed`), a fixed
  `DUNNING_SCHEDULE_DAYS` constant driving the 0/3/5/7-day ladder, lease-based
  distributed processing to prevent double-processing, `last_failure_code`
  captured from Stripe, `notification_attempts` tracking, and autopay-disable on
  terminal (`dunned`) state.
- `ACHReturn` domain model already exists (per the codebase inventory) with
  failure-code tracking and at least one flagged unsupported case
  (`unsupported_partial_ach_return`) — the model exists but is not yet wired into
  a distinct retry/notification path from card declines.
- Both card declines and ACH failures currently appear to feed the same
  `DunningState` ladder without branching on payment method type or decline
  category.

## Goals

- Retry timing adapts to the specific decline/return reason instead of a single
  fixed schedule (e.g., "insufficient funds" retries sooner than "expired card,"
  which should prompt an update-payment-method notification instead of a blind
  retry).
- ACH returns get a distinct handling path from card declines: different codes
  (R01 insufficient funds, R02 account closed, R04 invalid account number, etc.),
  different clearing timelines (ACH returns can take longer to post than a card
  decline), and different customer messaging (a returned ACH payment may carry an
  NSF-style implication that a declined card does not).
- Preserve the existing lease-based distributed processing and autopay-disable-on-
  terminal behavior — this extends the existing `DunningState` machine, it doesn't
  replace it.

## Non-Goals

- No card-account-updater integration in this slice (verifying Stripe's card
  account updater is active on Connect charges is a smaller, separate
  operational check, not a feature build — track separately, not as part of this
  requirements doc).
- No changes to the underlying Stripe charge/PaymentIntent creation logic — this is
  entirely about what happens *after* a decline/return event, not how charges are
  initiated.

## Requirements

### R1. Decline-code classification
- On a card decline, classify `last_failure_code` (already captured) into a
  retry-strategy bucket: `retry_soon` (e.g., insufficient_funds, temporary issuer
  decline), `retry_later` (e.g., processing_error), `no_retry_needs_update`
  (e.g., expired_card, lost_card, stolen_card, do_not_honor with high repeat
  count).
- Classification is a lookup table (decline code → bucket), not hardcoded
  per-decline branching logic scattered through the codebase — one place to
  update as Stripe's decline taxonomy evolves.

### R2. Smart retry schedule
- Replace (or extend, if backward-compat is needed during rollout) the fixed
  `DUNNING_SCHEDULE_DAYS` ladder with a schedule keyed by retry-strategy bucket:
  - `retry_soon`: shorter intervals (e.g., 1, 3, 5 days)
  - `retry_later`: longer intervals (e.g., 3, 7, 14 days)
  - `no_retry_needs_update`: skip automated retry entirely, go straight to a
    "please update your payment method" notification and hold in a distinct
    `awaiting_payment_method_update` sub-state, rather than burning retry attempts
    against a card that cannot succeed.

### R3. ACH-return branch
- ACH failures route through a distinct `ACHReturnDunning` path (or a
  payment-method-aware branch of the same `DunningState` machine — implementation
  detail, but the *behavior* must differ):
  - Return-code-aware messaging (e.g., R01 insufficient funds vs. R02 account
    closed vs. R04 invalid account number get different parent-facing copy).
  - Longer clearing-aware retry windows reflecting ACH's slower settlement vs. card
    (do not retry an ACH charge on the same short cadence as a card decline).
  - Explicit handling for the existing flagged gap: partial ACH returns
    (`unsupported_partial_ach_return`) must have a defined behavior (even if that
    behavior is "flag for manual admin review" rather than full automation in this
    first slice) rather than remaining unhandled.

### R4. Notification content by category
- Parent-facing dunning notifications differ by bucket: a retryable decline gets
  "we'll try again on [date]," a needs-update decline gets "please update your
  payment method," an ACH return gets return-code-appropriate messaging (and,
  if the academy's fee policy includes an NSF-style fee for returned ACH
  payments — a business decision, see Open Decisions — that fee is disclosed
  clearly, separate from a card decline which typically carries no such fee).

### R5. Preserve existing terminal behavior
- `dunned` terminal state and autopay-disable-on-terminal behavior remain
  unchanged in shape — only the path/timing to reach that terminal state changes
  based on classification.

## Data Model Changes

### `DunningState` (extend existing)
```text
retry_strategy_bucket: "retry_soon" | "retry_later" | "no_retry_needs_update" |
  "ach_return" | null
decline_code_classified: string    # the raw code that drove the classification
sub_status: "awaiting_payment_method_update" | null   # for no_retry_needs_update
```

### New `decline_code_classifications` (config/lookup table, not per-invoice)
```text
decline_code: string
payment_method_type: "card" | "ach"
bucket: "retry_soon" | "retry_later" | "no_retry_needs_update"
retry_schedule_days: [int]
```

### `ACHReturn` (extend existing)
```text
return_code: string                # R01, R02, R04, etc.
dunning_state_id: string            # link to the DunningState this return drove
nsf_fee_applied_cents: int | null   # if academy fee policy includes one
partial_return_handling: "manual_review" | "auto_handled"   # resolves the
  existing unsupported_partial_ach_return gap explicitly, at least to a known
  fallback behavior
```

## Dependencies

- None on other roadmap items — extends existing `DunningState`/`ACHReturn`
  models directly. Can proceed independently of the billing-invoice-line items.
- If payment plan installments (roadmap item 4) ship first, this work
  automatically improves installment-failure handling too, since both reuse the
  same `DunningState` machine.

## Open Decisions

1. Does a returned ACH payment carry an NSF-style fee to the parent by academy
   policy, and if so, is that fee amount admin-configurable per academy (matching
   the pattern used for the existing ACH cash-discount policy)?
2. For `no_retry_needs_update` declines, does the system auto-disable autopay
   immediately, or wait for the update-payment-method notification to go unanswered
   for some grace period first?
3. What is the exact decline-code → bucket mapping? (Requires enumerating Stripe's
   current decline code list and categorizing each — a data-gathering task, not a
   design decision, but should be done before implementation starts.)
4. For partial ACH returns, is "flag for manual admin review" acceptable as the
   long-term behavior, or is this only a stopgap pending full automation?

## Acceptance Criteria / Test Cases

- A card decline with code `insufficient_funds` retries on the `retry_soon`
  schedule (1/3/5 days), not the old fixed 0/3/5/7 ladder.
- A card decline with code `expired_card` does not attempt an automatic retry;
  instead it produces an "update your payment method" notification and enters
  `awaiting_payment_method_update`.
- An ACH return with code `R01` follows the ACH-specific retry path (not the card
  schedule) and produces return-code-appropriate parent messaging.
- A partial ACH return is explicitly flagged for manual admin review rather than
  silently failing or being treated identically to a full card decline.
- Existing `dunned`-state and autopay-disable-on-terminal behavior is unchanged
  for any bucket that reaches the terminal state.
- Existing lease-based distributed processing still prevents double-processing
  under the new branching logic.
