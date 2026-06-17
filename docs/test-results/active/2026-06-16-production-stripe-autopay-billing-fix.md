# production Stripe autopay billing fix

## Current State

Status: active

## Problem

After Stripe autopay Checkout success, backend does not persist active autopay/portal-ready state; verify webhook idempotency, reconciliation fallback, parent payments UI, and duplicate prevention.

## Changed Files

- `backend/v2/composition/admin.py`
- `backend/v2/composition/parent.py`
- `backend/v2/contexts/billing/application/ports.py`
- `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py`
- `backend/v2/contexts/billing/application/use_cases/parent_billing.py`
- `backend/v2/contexts/billing/domain/models.py`
- `backend/v2/contexts/billing/infrastructure/mongo_parent_billing_customer_repo.py`
- `backend/v2/contexts/billing/infrastructure/mongo_subscription_repo.py`
- `backend/v2/interfaces/parent/payment_routes.py`
- `backend/v2/interfaces/parent/views.py`
- `backend/v2/migrations/0129_parent_billing_customers.py`
- `backend/v2/tests/application/test_parent_billing_portal.py`
- `backend/v2/tests/application/test_webhook_handler.py`
- `backend/v2/tests/infrastructure/test_subscription_repo_persistence.py`
- `backend/v2/tests/interface/test_parent_sessions_checkout.py`
- `frontend/app/(parent)/parent/payments/page.tsx`
- `frontend/e2e/specs/qa-defects.spec.ts`
- `frontend/lib/api/parent.ts`
- `test_result.md`

## Log

- 2026-06-16T23:10:44 main/NA: Task ledger created.
- 2026-06-16T23:11:39 main/working: Started P0 Stripe autopay/portal investigation. Read README, DEPLOYMENT, backend/frontend/testing/feedback rules, billing active ledgers, billing plans, and tenant/billing ADRs. Spawned read-only parallel research threads A-D.
- 2026-06-16T23:28:48 main/working: Implemented tenant-scoped parent_billing_customers persistence, subscription checkout session persistence, webhook checkout fallback, checkout-status reconciliation, pending checkout reuse, portal customer resolution, and parent payments success-return polling.
- 2026-06-17T00:05:20 main/working: Fixed Docker SaaS staging Stripe webhook wiring: added saas_staging.sh stripe-listen helper to capture sandbox webhook secret, persist ignored local Stripe env, restart backend, and forward real sandbox webhook events.
- 2026-06-17T00:48:39 main/working: Started focused subscription invoice ledger convergence pass: reading required ADRs/plans, tracing webhook and ledger write paths before edits.
## Verification

- No verification recorded yet.
- 2026-06-16T23:28:48: RED first: pytest backend/v2/tests/application/test_parent_billing_portal.py backend/v2/tests/infrastructure/test_subscription_repo_persistence.py -q failed 6 expected tests before implementation.
- 2026-06-16T23:28:48: Focused backend: source backend/.venv/bin/activate && pytest backend/v2/tests/application/test_parent_billing_portal.py backend/v2/tests/infrastructure/test_subscription_repo_persistence.py backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/interface/test_parent_sessions_checkout.py -q => 47 passed, 1 warning.
- 2026-06-16T23:28:48: Webhook/idempotency contracts: source backend/.venv/bin/activate && pytest backend/v2/tests/contract/test_stripe_event_dedup.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py backend/v2/tests/contract/test_billing_idempotency.py -q => 25 passed.
- 2026-06-16T23:28:49: Frontend typecheck: cd frontend && pnpm typecheck => passed.
- 2026-06-16T23:28:49: Frontend production build: cd frontend && pnpm build => passed with existing lint warnings only.
- 2026-06-16T23:28:49: Targeted E2E: cd frontend && pnpm exec playwright test e2e/specs/qa-defects.spec.ts --project=chromium-mobile --grep 'autopay|billing portal' => 4 passed.
- 2026-06-16T23:28:49: Backend lint/format: source backend/.venv/bin/activate && ruff format --check <touched backend files>; ruff check <touched backend files> => passed.
- 2026-06-16T23:28:49: Manual Stripe CLI/browser webhook forwarding not run in this session; launch proof still needs staging/local Stripe webhook checkout evidence before production cutover.
- 2026-06-17T00:05:20: Docker SaaS staging Stripe wiring: scripts/dev/saas_staging.sh stripe-listen rebuilt/restarted backend; curl http://127.0.0.1:8001/api/v2/healthz => ok; backend container env has STRIPE_API_KEY/STRIPE_WEBHOOK_SECRET and V2_* equivalents set.
- 2026-06-17T00:07:36: SaaS staging helper verification: scripts/dev/saas_staging.sh stripe-listen configures ignored .local Stripe sandbox env, rebuilds/restarts backend, reaches health, and holds open forwarding to /api/v2/parent/webhooks/stripe. Diagnostic listener was stopped before handoff; rerun helper in a terminal while testing.
- 2026-06-17T00:18:22: Real Docker staging Stripe webhook replay for Adhvik: checkout.session.completed/invoice.paid/payment_intent.succeeded accepted and processed; after handler fix and local event reset, payments contains succeeded row 01KVA058CB0SFZHZFXZ1P0MDDS linked to enrollment enr_std_blno_012_adhvik__thu_intermediate amount 7000.
## Reusable Lessons

- None recorded yet.
