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

## Rework pass — review fixes (2026-07-01)

Three reviewers (quality, security, boundary) reviewed this branch's diff vs
main ref `a50c9e5e`. No CRITICAL/blocking findings; 4 real gaps fixed below.
Commit `80e89504` (original Slice I) left untouched — this is a new commit on
top. Scope: exactly the 4 items below, 7 files touched, nothing else.

### 1. [HIGH quality] Type-unsafe `connected_accounts: Any` bridge
`handle_webhook_event.py` accepted `connected_accounts: Any | None`, the raw
binding for the `_ConnectAccountResolver` shim in `composition/parent.py`
(bridges the repo's `get_by_stripe_account_id` to the handler's expected
`academy_id_for_account` — the "Slice-B lesson": an untyped port/repo name
mismatch previously reached production).

Fix: added a local `AccountAcademyResolver(Protocol)` in
`handle_webhook_event.py` (next to `HandleWebhookEvent`, since this is a
handler-specific bridging shape, not a real repo port that belongs in
`ports.py`):
```python
class AccountAcademyResolver(Protocol):
    async def academy_id_for_account(self, stripe_account_id: str) -> str | None: ...
```
`HandleWebhookEvent.__init__`'s `connected_accounts` param is now typed
`AccountAcademyResolver | None` instead of `Any | None`. Verified
`_ConnectAccountResolver` (composition) and `_FakeConnectAccountResolver`
(test) both structurally satisfy it, and that `main.py`'s
`MongoConnectedAccountRepository(db)` is correctly bound to
`StartConnectOnboarding` (a different port), not to `HandleWebhookEvent` — so
no accidental mismatch existed, but one is now caught by the type checker if
ever introduced.

### 2. [HIGH quality] Cross-tenant isolation of `get_by_stripe_account_id` untested against the real repo
Read `mongo_connected_account_repo.py`: `get_by_stripe_account_id` is
deliberately **tenant-scoped** (goes through `TenantScopedRepository._find_one`,
which ANDs in `current_academy_id()`), not a global/unscoped lookup. The
webhook guard works because `_ConnectAccountResolver.academy_id_for_account`
wraps the call in `tenant_scope(self._academy_id)` — the running handler's
OWN academy — then asks "does this stripe_account_id belong to MY academy?".
A foreign academy's id naturally resolves to `None` rather than ever
returning that academy's document.

Fix: added
`test_get_by_stripe_account_id_never_resolves_another_academys_account` to
`tests/contract/test_connected_account_repo.py`, against the REAL
`MongoConnectedAccountRepository` (not a fake). Proves, for both directions
(A resolving A/B, B resolving B/A): each academy resolves its own
`stripe_account_id` correctly, and resolving another academy's
`stripe_account_id` while scoped to a different academy returns `None`
rather than cross-attributing the document. This is in addition to (not a
replacement for) the pre-existing general `test_tenant_isolation_between_academies`.

### 3. [LOW quality+security] Non-unique index on `stripe_account_id`
`migrations/0139_connected_accounts.py` had a unique index on `academy_id`
but only a plain lookup index on `stripe_account_id` — the exact field the
webhook Connect-account guard trusts to resolve tenant identity.

Fix: made the `stripe_account_id` index `unique=True, sparse=True` (same
`unique+sparse` pattern as migration 0138's
`invoices_academy_invoice_number_unique`, for the same reason: defense in
depth at the DB layer, sparse so it never collides on absent values). Index
name unchanged (`academy_connected_accounts_stripe_account`). Added
`test_stripe_account_index_is_unique_and_sparse` and
`test_rejects_duplicate_stripe_account_id_across_academies` to
`tests/contract/test_connected_accounts_migration.py`.

### 4. [MEDIUM quality+security] Unhandled `ValueError` on academy-id mismatch → raw 500
`connect_onboarding.py`'s `StartConnectOnboarding.start()` raised a bare
`ValueError("academy_id mismatch for connect onboarding")` on mismatch, with
no handling in `connect_routes.py` — would have surfaced as an unhandled 500.

Checked `require_platform_admin` (`bootstrap_routes.py`): it already returns
`HTTPException(status_code=404, detail="Not found")` for the non-platform-admin
case specifically to avoid confirming/denying anything to an unauthorized
caller. Matched that convention exactly rather than inventing a new one.

Fix: added `AcademyMismatchError(DomainError)` to
`contexts/billing/domain/errors.py` (`code="Billing.AcademyMismatch"`,
`status_code=404`), following this codebase's established
`DomainError`-subclass pattern (verified `register_exception_handlers` is
wired app-wide in `main.py`, so `DomainError` subclasses are translated to
JSON automatically — the route layer is not supposed to catch these
explicitly, per `shared/http/errors.py`'s own docstring). Changed
`connect_onboarding.py` to `raise AcademyMismatchError(...)` instead of
`ValueError`. No route-level try/except needed — this is the existing
convention, not a new one. Added
`test_start_onboarding_academy_mismatch_returns_clean_4xx_not_500` to
`tests/interface/test_platform_connect_routes.py`, asserting a 404 with
`error.code == "Billing.AcademyMismatch"` (not a 500) and that the use case
was still called with the mismatched academy_id from the path.

### Files touched (7)
```
backend/v2/contexts/billing/application/use_cases/connect_onboarding.py
backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py
backend/v2/contexts/billing/domain/errors.py
backend/v2/migrations/0139_connected_accounts.py
backend/v2/tests/contract/test_connected_account_repo.py
backend/v2/tests/contract/test_connected_accounts_migration.py
backend/v2/tests/interface/test_platform_connect_routes.py
```
Nothing else touched: Stripe Connect design decisions (Accounts v2,
`on_behalf_of`, destination charges, `application_fee_amount=0`), legacy
webhook branches, and everything else out of scope for these 4 findings.

### DoD output (rework pass)

```
PYTHONPATH=. python -m pytest backend/v2/tests -q
  => 1 failed, 1880 passed, 5 warnings
     ONLY failure: test_bootstrap_source_does_not_reference_default_academy_id
     (same pre-existing cwd-relative-path bug as before this rework — unrelated)

ruff check backend/v2          => All checks passed!
ruff format --check backend/v2 => 736 files already formatted
lint-imports --config backend/pyproject.toml => Contracts: 4 kept, 0 broken.
```

New test count: 4 new tests added for this rework pass:
- `test_get_by_stripe_account_id_never_resolves_another_academys_account`
  (`test_connected_account_repo.py`) — item 2
- `test_stripe_account_index_is_unique_and_sparse` and
  `test_rejects_duplicate_stripe_account_id_across_academies`
  (`test_connected_accounts_migration.py`) — item 3
- `test_start_onboarding_academy_mismatch_returns_clean_4xx_not_500`
  (`test_platform_connect_routes.py`) — item 4

Full suite went from 1876 passed (original Slice I doc, above) to 1880
passed on this rework pass; the 4-test delta matches exactly.
