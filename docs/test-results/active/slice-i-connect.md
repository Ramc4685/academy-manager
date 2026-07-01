# Slice I — Stripe Connect per academy (foundation)

Branch: `slice/i-stripe-connect` (based on main `a50c9e5e`)
Date: 2026-07-01

## Problem / goal

Make each academy its own merchant-of-record; all autopay fund flow routes
through its connected Stripe account (destination charges + `on_behalf_of`).
Foundation slice for later autopay slices (C idempotency, E fees, G ACH).

## What was built

### Domain
- `backend/v2/contexts/billing/domain/connected_account.py` — `ConnectedAccount`
  frozen aggregate (`academy_id`, `stripe_account_id`, `status`, `capabilities`,
  `charges_enabled`, `payouts_enabled`, timestamps). `new()`, `with_status()`,
  `is_ready_for_charges()`. Pure domain, no infra imports.

### Infrastructure
- `backend/v2/contexts/billing/infrastructure/mongo_connected_account_repo.py` —
  `MongoConnectedAccountRepository` on collection `academy_connected_accounts`,
  extends `TenantScopedRepository` (S0 pattern). `get_for_academy`,
  `get_by_stripe_account_id`, `upsert`, `update_status`.
- `stripe_gateway.py` (`RealStripeGateway`):
  - `create_connected_account` — Accounts v2 (`stripe.v2.core.accounts.create`)
    with `controller` props (`losses.payments=application`, `fees.payer=account`,
    `stripe_dashboard.type=full`, `requirement_collection=stripe`). NO legacy `type`.
  - `create_account_onboarding_link` — hosted AccountLink (`type=account_onboarding`).
  - `create_off_session_payment_intent` — new `connected_account_id` param adds
    `on_behalf_of` + `transfer_data.destination` + `application_fee_amount=0`
    (destination charge). Customer stays on platform (no `stripe_account`).
  - `create_autopay_setup_checkout_session` — new `connected_account_id` param
    sets `setup_intent_data.on_behalf_of`. Customer created on platform.
  - `payment_method_types` never passed anywhere (dynamic payment methods).
- `fake_stripe_gateway.py` — records `connected_accounts` (with controller
  params), `account_onboarding_links`, `off_session_payment_intents` (with
  `on_behalf_of`/`transfer_data`), threads `connected_account_id` through setup
  checkout — so tests can assert Connect params.

### Application
- `application/ports.py` — added `ConnectedAccountRepository` port; extended
  `StripeGateway` Protocol with `create_connected_account`,
  `create_account_onboarding_link`, `create_off_session_payment_intent` (with
  `connected_account_id`), and the setup-checkout `connected_account_id` param.
- `application/use_cases/connect_onboarding.py` — `StartConnectOnboarding`:
  creates+persists the connected account on first run, reuses it after, always
  mints a fresh onboarding link. Idempotent.
- `application/use_cases/handle_webhook_event.py` — new `connected_accounts`
  resolver param; `resolve_academy_for_event` + `_validate_event_guards_async`
  resolve Connect events (top-level `account`) to the owning academy via the
  repo, quarantining unknown/mismatched accounts. Wired into `process_next`.
  **Legacy branches left untouched (Slice A owns their removal).**

### Interface
- `backend/v2/interfaces/platform/connect_routes.py` — platform-admin BFF route
  `POST /api/v2/platform/academies/{academy_id}/connect/onboarding`. Tenant
  resolved explicitly from the path, `require_platform_admin` guard, goes
  through `app.state.platform_connect_onboarding` (no infra/domain import).
  Registered in `platform/router.py`.

### Composition / wiring
- `composition/parent.py` — `_ConnectAccountResolver` shim bridges repo's
  `get_by_stripe_account_id` → webhook's `academy_id_for_account`; wired into
  both `HandleWebhookEvent` constructions.
- `main.py` — wires `StartConnectOnboarding` + `MongoConnectedAccountRepository`
  into `app.state.platform_connect_onboarding`.

### Migration
- `backend/v2/migrations/0139_connected_accounts.py` — creates
  `academy_connected_accounts`, unique index on `academy_id`, index on
  `stripe_account_id`, JSON-schema validator (moderate/error). Idempotent.

## Tests (all new, TDD-first)
- Unit: `tests/unit/test_connected_account.py` (6) — domain invariants.
- Contract: `tests/contract/test_connected_account_repo.py` (7) — upsert,
  get-by-academy, get-by-stripe-id, status update, **tenant isolation**, port.
- Contract: `tests/contract/test_stripe_gateway_request_shape.py` (5) — Connect
  params present on off-session PI + setup checkout, `payment_method_types`
  absent, account creation uses controller props not legacy `type`.
- Application: `tests/application/test_webhook_connect_tenant_resolution.py` (5)
  — account→academy resolution, quarantine on unknown/mismatch, non-Connect
  fallback.
- Interface: `tests/interface/test_platform_connect_routes.py` (3) — happy path,
  tenant-from-path (not claims), non-platform-admin rejected (404).
- Contract: `tests/contract/test_connected_accounts_migration.py` (4) —
  idempotent, unique academy index, one account per academy.
- Contract: `tests/contract/test_connect_composition_wiring.py` (2) — REAL repo
  driven through the use case + through the webhook resolver shim (Slice B
  name-mismatch guard).

## DoD output

```
PYTHONPATH=. python -m pytest backend/v2/tests -q
  => 1 failed, 1876 passed, 5 warnings
     ONLY failure: test_bootstrap_source_does_not_reference_default_academy_id
     (pre-existing cwd-relative-path bug — FileNotFoundError on
      'v2/contexts/identity/.../bootstrap_academy.py'; unrelated to this slice)

ruff check backend/v2         => All checks passed!
ruff format --check backend/v2 => 736 files already formatted
lint-imports --config backend/pyproject.toml => Contracts: 4 kept, 0 broken.
```

## Deviations / notes
- The `execute()` webhook path (legacy, non-queued) was left calling the sync
  guard; the Connect account guard runs in the canonical `process_next` path
  (async). No behavior change for existing platform events.
- Connect account country hardcoded to `us` in the gateway (matches current
  single-country launch); revisit for multi-country in a later slice.
