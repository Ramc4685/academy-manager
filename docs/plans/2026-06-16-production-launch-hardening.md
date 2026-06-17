# Production Launch Hardening Plan

Date: 2026-06-16

## Current Behavior Found

- v2 settings already include `V2_SAAS_MODE`; this branch wires the launch-mode names `APP_TENANCY_MODE`, `PRIMARY_ACADEMY_ID`, `ENABLE_PLATFORM_ROUTES`, `ENABLE_OWNER_ROLE`, and `ENABLE_STUDENT_LOGIN`.
- `TenancyMiddleware` resolves tenants from the request and does not use `default_academy_id`, but it does not yet enforce single-academy launch mode.
- `compose_parent()` and `compose_parent_webhook_handler()` still fall back to `settings.default_academy_id` when an academy is not passed.
- Parent billing portal reads `users.stripe_customer_id` by parent id only inside the parent composition helper; this needs tenant-scoped lookup and no global email/customer fallback.
- Stripe webhook handling already stores events asynchronously and has tenant mismatch quarantine tests, but composition can still instantiate the handler with a default academy.
- Admin reports, invoice artifact helpers, audit helpers, and export helpers are concentrated in `backend/v2/composition/admin.py`.
- Coach roster writes and coach billing enrollment moves are still mounted under the coach BFF.

## Files Likely Affected

- `backend/v2/shared/config/settings.py`
- `backend/v2/shared/auth/middleware.py`
- `backend/v2/composition/parent.py`
- `backend/v2/contexts/billing/application/use_cases/parent_billing.py`
- `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py`
- `backend/v2/composition/admin.py`
- `backend/v2/interfaces/admin/*`
- `backend/v2/interfaces/coach/router.py`
- `backend/v2/interfaces/coach/billing_enrollment_routes.py`
- `backend/v2/interfaces/coach/roster_routes.py`
- `backend/v2/tests/unit/test_settings.py`
- `backend/v2/tests/unit/test_tenancy_middleware.py` or nearest existing middleware tests
- `backend/v2/tests/application/test_parent_billing_portal.py`
- `backend/v2/tests/application/test_webhook_handler.py`
- focused admin/coach/interface tests near the touched routes

## Proposed Change

1. Add launch-mode config:
   - `APP_TENANCY_MODE=single_academy`
   - `PRIMARY_ACADEMY_ID=<configured academy id>`
   - `ENABLE_PLATFORM_ROUTES=false`
   - `ENABLE_OWNER_ROLE=false`
   - `ENABLE_STUDENT_LOGIN=false`
   - Platform route mounting must be gated by `ENABLE_PLATFORM_ROUTES`.
2. Enforce single-academy mode in request tenancy:
   - Resolved tenant must equal `PRIMARY_ACADEMY_ID`.
   - Mismatch returns `403 Forbidden`.
   - Missing `PRIMARY_ACADEMY_ID` in single-academy mode fails configuration.
3. Remove unsafe parent/webhook default-academy composition fallback:
   - Parent composition and webhook composition must require an explicit academy id.
   - Stripe customer persistence and portal lookup stay scoped by academy and parent id.
4. Harden webhook processing:
   - Safe tenant resolution must come from persisted mappings or event metadata matching the handler tenant.
   - Events without a safe tenant remain received/quarantined and must not mutate tenant data.
5. Follow-on slices:
   - Admin reports/audit/invoice artifacts/export permission and tenant scoping.
   - Coach billing move route removal and roster-write denial if the matrix denies it.
   - Enrollment fallback lookup tenant filter.
   - Platform governance grant/revoke/audit tenant validation.
   - Public registration pending/inactive membership behavior or documented durable rate-limit gap.
   - Static checks expanded to cover composition files.

## Risks

- Full P0/P1 scope is broad and touches multiple personas; safest execution is one verified slice at a time.
- Some existing tests may assume default-academy composition fallbacks for local convenience.
- Webhook requests are unauthenticated, so tenant resolution must not depend on request membership.
- Disabling coach routes may require frontend cleanup later; for launch safety, backend denial is authoritative.

## Verification Steps

- Start with failing tests for launch config and single-academy mismatch.
- Add failing tests for explicit parent/webhook academy composition and tenant-scoped portal/customer behavior.
- Run focused tests after each slice:
  - `cd backend && source .venv/bin/activate && pytest v2/tests/unit/test_settings.py v2/tests/unit/test_tenancy_middleware.py -q`
  - `cd backend && source .venv/bin/activate && pytest v2/tests/application/test_parent_billing_portal.py v2/tests/application/test_webhook_handler.py -q`
- Run `ruff format --check` and `ruff check` for touched backend files.
- Before handoff, run `git status --short --branch` and `git diff`, then record results in the active test ledger.
