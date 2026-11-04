# `platform` context: tenants, platform billing, audit, governance

## One plan model: `PlatformPlan` + `TenantSubscription` is the source of truth

Two plan shapes exist side by side:

- `Tenant.plan_code` and `TenantLimits` (`domain/models.py`), written by
  `tenant_lifecycle.py`, shown and edited on the platform tenant pages
  (`interfaces/platform/bootstrap_routes.py`, `frontend/app/(platform)/platform/tenants`).
- `PlatformPlan` and `TenantSubscription` (`billing/domain/models.py`), the
  Stripe Billing shape with `monthly_price_cents`, `stripe_price_id`,
  `billing_status` and trial state.

Decision (AI strategy plan, section 5, 2026-11-04): the Growth tier is a
`PlatformPlan` sold through `TenantSubscription` and Stripe Billing, so
**`PlatformPlan` and `TenantSubscription` are the source of truth for
entitlements.** `Tenant.plan_code` and `TenantLimits` stay as a display label
and operator notes only: nothing may gate a feature or enforce a limit from
them. They are kept, not deleted, because the tenant routes and pages read
them.

## Entitlements: `has_feature`

`HasFeature.execute(academy_id, feature)` in
`billing/application/use_cases/manage_platform_billing.py` resolves the
academy's `TenantSubscription` (`billing_status` in `trialing` or `active`)
to its `PlatformPlan` (status `active`) and answers whether `feature` is in
`PlatformPlan.features` (`frozenset[str]`, default empty, set through
`PUT /api/v2/platform/billing/plans/{plan_id}`). No subscription, a
cancelled or unpaid one, or an archived plan all answer `False`. The first
feature name is `"ai"`.
