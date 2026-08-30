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
  `expired_at`) and the call returns `None`, so the caller re-quotes and the
  audit trail records why. Legacy snapshots without `expires_at` remain
  consumable so in-flight quotes are not bricked by the deploy.
- Registration `create_checkout_session()` sets Stripe `expires_at` to
  31 minutes (Stripe's 30-minute floor plus clock-skew margin), so a stale
  quote can no longer be paid up to ~24h later. Expiry rides the existing
  `checkout.session.expired` webhook handling and CHECKOUT_EXPIRED re-quote
  path.

## Deploy notes
No migration and no new indexes — `EXPIRED`/`expired_at` are written into
the existing `billing_calculation_snapshots` collection. Behaviour change:
registration checkout links now expire 31 minutes after creation; a parent
who returns later gets Stripe's expired-session page and restarts checkout
for a fresh quote.
