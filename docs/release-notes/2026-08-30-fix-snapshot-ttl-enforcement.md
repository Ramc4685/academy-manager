# snapshot-ttl-enforcement

PR: #574

## What changed
The 15-minute quote TTL on `BillingCalculationSnapshot` was decorative
(issue #530): `consume()` matched any OPEN snapshot with no `expires_at`
check, the `EXPIRED` status was never written anywhere, and the registration
Checkout Session was created with Stripe's ~24h default lifetime while the
snapshot was consumed at session creation rather than payment. A parent
could therefore leave the Checkout tab open and pay the stale
`final_amount_cents` frozen into the session many hours after quoted
occurrences had elapsed or been cancelled — while the audit snapshot still
claimed those classes were billable.

Two changes close the window:

- `consume()` now enforces the TTL in its atomic OPEN→CONSUMED predicate.
  An OPEN snapshot past `expires_at` is stamped `EXPIRED` (with
  `expired_at`) and the call returns `None`. The registration checkout
  callers now honor that refusal: consume runs BEFORE the Stripe Checkout
  Session is minted, and a `None` raises the new typed
  `Billing.QuoteExpired` error (409) so the parent re-quotes instead of a
  session being created against a snapshot the audit trail says is
  EXPIRED. Legacy snapshots without `expires_at` remain consumable so
  in-flight quotes are not bricked by the deploy. `compose_parent` also
  passes its clock through to the payment repo so quoting and TTL
  enforcement judge time identically.
- Registration `create_checkout_session()` sets Stripe `expires_at` to
  31 minutes (Stripe's 30-minute floor plus clock-skew margin), so a stale
  quote can no longer be paid up to ~24h later. Expiry rides the existing
  `checkout.session.expired` webhook handling and CHECKOUT_EXPIRED re-quote
  path.

## Risk / rollback
Low risk. The TTL predicate only affects `consume()`, whose sole callers
quote and consume within the same request today — so `Billing.QuoteExpired`
(409) can only surface on a genuine race or stall longer than the 15-minute
TTL, and a retry simply mints a fresh quote. Legacy docs without
`expires_at` are explicitly still consumable. The 31-minute Stripe expiry
uses the platform's supported `expires_at` parameter and reuses the
existing expired-session handling. Rollback: revert the PR — no data
migration to undo; any snapshots stamped `EXPIRED` in the interim stay
terminal, which is correct (they were past TTL).

## Deploy notes
No migration and no new indexes — `EXPIRED`/`expired_at` are written into
the existing `billing_calculation_snapshots` collection. Behaviour change:
registration checkout links now expire 31 minutes after creation; a parent
who returns later gets Stripe's expired-session page and restarts checkout
for a fresh quote.
