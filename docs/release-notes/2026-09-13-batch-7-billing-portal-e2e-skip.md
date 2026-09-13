# Batch 7: billing-portal E2E prerequisite fix

## What changed

- Fixes #595 — `local-auth-qa.spec.ts` hard-asserted the "Start autopay for
  an enrollment first" billing-portal banner, which the app only renders
  once Stripe is configured and the parent simply has no Stripe customer
  yet. A default seeded local-staging stack has no `STRIPE_API_KEY`, so
  `POST /parent/billing/portal` failed on configuration and the app fell
  through to a generic error banner instead, failing the spec on every
  local run.
- Root cause went one level deeper than the missing-config case: with no
  `STRIPE_API_KEY` the stack runs `FakeStripeGateway`, whose portal call
  previously succeeded unconditionally, so the endpoint returned a fake
  redirect and the payments page navigated to a dead `fake.stripe.com` URL
  instead of ever rendering a banner. `CreateCustomerPortalSession` now
  raises `BillingPortalNotReady` (409, `Billing.BillingPortalNotReady`)
  whenever the parent has no stored Stripe customer, before any gateway is
  touched — this prerequisite was previously folded into
  `CheckoutCreationFailed` (502), which was indistinguishable from "the
  academy's Stripe integration is broken."
- `FakeStripeGateway.create_customer_portal_session` now mirrors the real
  gateway's behavior and refuses a missing customer id, so local-staging
  and CI exercise the same prerequisite path as production.
- The frontend maps the new `Billing.BillingPortalNotReady` code to the
  existing "Start autopay for an enrollment first" prerequisite copy; the
  now-unreachable `isStripeUnconfiguredPortalMessage` helper was removed.
- `local-auth-qa.spec.ts` now asserts the prerequisite banner directly
  against a default seeded stack — no skip and no runbook detour needed,
  since the fix makes the real prerequisite path deterministic regardless
  of whether `STRIPE_API_KEY` is set.

## Deploy notes

No migrations. No manual steps. The new `BillingPortalNotReady` error code
is additive (a new 409 case) and does not change any existing success or
error response shape that other clients depend on.

## Risk / rollback

Low risk: the change narrows an existing 502 (`CheckoutCreationFailed`)
into a more specific 409 for one precondition, and adjusts a fake test
double to match real-gateway semantics. Rollback is a straight revert of
this PR; no data or migration cleanup is required.

PR: #812
