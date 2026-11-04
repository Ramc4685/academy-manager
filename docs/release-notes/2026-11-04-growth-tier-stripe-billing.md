# growth-tier-stripe-billing

PR: #TBD

## What changed
Academy owners now see a "Your CourtMastr plan" card on Settings > Integrations: the current plan (or free core operations) and the Growth offer ($99 a month, 0 bps processing markup, AI features) with an "Upgrade to Growth" button that opens Stripe Billing Checkout on the platform account. The Stripe webhook keeps the academy's platform subscription current (status, period, cancel at period end), which is what `has_feature(academy, "ai")` reads, and the upgrade is instrumented with two platform audit events (`tenant.plan_upgrade_started` with the academy's 90-day Stripe volume, `tenant.plan_activated`).

## Deploy notes
Migration 0221 seeds two plan rows (`growth` at $99 with the `ai` feature, `flat` at $49) and never overwrites an existing row with the same code. The owner must create the Growth price in Stripe test mode and PUT its id on the plan through `PUT /api/v2/platform/billing/plans/plan_growth` (`stripe_price_id`); until then the card shows "Growth checkout is not open yet". The platform webhook endpoint must receive `checkout.session.completed` and `customer.subscription.*` (it already does). Flat is assigned per academy by the owner through the existing platform activate route. Test-mode verification of the checkout must run on staging or a test environment: production quarantines webhook events whose `livemode` is false, so a test-mode Growth checkout never syncs on prod. Nothing live is changed: no live Stripe, Fly or production DB change is part of this PR.

## Risk / rollback
If the webhook sync misreads a Stripe status the academy's `ai` entitlement could be on or off wrongly; the row is a pure projection of the Stripe object, so replaying the event or activating/cancelling through the platform billing routes corrects it. Events carrying `metadata.source == "platform_plan"` are routed away from the parent-tuition handlers; every other event path is unchanged. Rollback: revert the PR; the two seeded plan rows are inert without a `stripe_price_id`, and any `platform_tenant_subscriptions` row the sync wrote can be cancelled through `POST /api/v2/platform/billing/tenants/{academy_id}/cancel-now`.
