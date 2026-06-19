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
- 2026-06-17T01:52:02 main/working: Continuing delegated subscription invoice ledger convergence pass. Read AGENTS kickoff, README, DEPLOYMENT, backend/testing/feedback rules, ADR-0011/0012, billing convergence plan, and subscription-specific plan; comparing existing WIP against acceptance criteria before further edits.
- 2026-06-17T02:14:10 main/working: Implemented subscription invoice ledger convergence hardening: explicit stripe_invoice_id fields, tenant enrollment identity validation, paid-obligation quarantine, invoice lookup/index support, send-invoice/autopay duplicate-charge guards, parent/admin read-model dedupe, and API-2026 fixture replay coverage.
- 2026-06-17T02:26:15 main/working: Addressed read-only code-review findings where in scope: invoice.payment_failed now syncs subscription invoices into the ledger as open receivables, admin payment/revenue lists dedupe legacy projections when matching ledger rows exist, and 0130 allocation idempotency index is partial like existing ledger index. Cross-writer autopay locking remains a residual launch risk beyond current re-read/idempotency guard.
- 2026-06-17T07:53:22 main/working: Started loop slice: ledger allocation replay repair for partial allocation writes. Evidence: mongo_billing_ledger_repo currently short-circuits existing allocation idempotency rows without repairing invoice/payment projections.
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
- 2026-06-17T01:00:27: RED: pytest backend/v2/tests/application/test_webhook_handler.py -q failed 4 expected subscription invoice ledger-convergence tests before implementation. GREEN: focused suite source backend/.venv/bin/activate && pytest backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/application/test_session_type_webhooks.py backend/v2/tests/contract/test_billing_idempotency.py backend/v2/tests/unit/test_charge_autopay_use_case.py backend/v2/tests/unit/test_send_invoice_use_case.py backend/v2/tests/contract/test_admin_directory_mongo_student_repo.py backend/v2/tests/interface/test_parent_sessions_checkout.py backend/v2/tests/application/test_parent_billing_portal.py -q => 93 passed, 1 known Starlette/httpx warning. Style: ruff format --check/check on touched backend files => passed.
- 2026-06-17T02:14:10: Post-format focused backend verification: pytest backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/contract/test_billing_idempotency.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py -q => 54 passed; pytest backend/v2/tests/unit/test_send_invoice_use_case.py backend/v2/tests/unit/test_charge_autopay_use_case.py -q => 30 passed; pytest backend/v2/tests/interface/test_admin_billing.py backend/v2/tests/interface/test_parent_sessions_checkout.py -q => 44 passed, 1 known Starlette/httpx deprecation warning; extra touched tests pytest backend/v2/tests/unit/test_parent_composition.py backend/v2/tests/contract/test_admin_directory_mongo_student_repo.py::test_get_admin_student_includes_enrollment_linked_paid_ledger_invoice_once backend/v2/tests/infrastructure/test_stripe_gateway_request_shape.py -q => 11 passed; backend ruff format --check v2 and ruff check v2 => passed.
- 2026-06-17T02:16:16: Post self-review rerun: ruff format --check v2 => 652 files already formatted; ruff check v2 => All checks passed; pytest webhook/idempotency/fixture group => 54 passed; send-invoice/autopay group => 30 passed; admin/parent interface group => 44 passed with known Starlette/httpx warning; extra parent composition/admin student/gateway tests => 11 passed.
- 2026-06-17T02:25:31: After code-review fixes: ruff format --check v2 => 652 files already formatted; ruff check v2 => All checks passed; pytest webhook/idempotency/fixture group => 55 passed; send-invoice/autopay group => 30 passed; admin/parent interface group => 44 passed with known Starlette/httpx warning; extra parent/admin composition/admin student/gateway tests => 24 passed.
- 2026-06-17T02:26:15: Final git hygiene: git diff --check => passed/no output; git diff --stat reviewed; git status --short --branch shows feat/stripe-subscription-ledger-convergence with expected modified/untracked implementation, tests, migration, fixture, plan, and active ledger files.
- 2026-06-17T06:13:25: Docker SaaS staging manual Stripe sandbox checkout verified on 2026-06-17: BLNO parent sakthivelplan@gmail.com started subscription checkout for enrollment enr_std_blno_001_athiksh_wed_intermediate; Stripe sandbox Checkout returned success session cs_test_a1Piv7YhQV6LBePxUIsyUUyAmMgM8Z1VMyhk4iwioORUyAVp5Nw5Ugh4pg; webhooks invoice.paid evt_1TjHMURMJDJBjoQz4RuK3Egr, payment_intent.succeeded evt_3TjHMRRMJDJBjoQz1E91k1Xr, checkout.session.completed evt_1TjHMVRMJDJBjoQzv27B6hHO processed; subscription active sub_1TjHMTRMJDJBjoQzDkSYUPBP; ledger invoice ledger-in_1TjHMRRMJDJBjoQzDGafFpf7 paid with balance_due_cents=0; legacy payment 01KVAMDF0ZEYWP2KXK5F51CJT3 succeeded; parent payment history shows new  succeeded payment; admin student Billing tab shows 2026-06 invoice PAID  paid//bin/zsh balance. Note: ledger_payments and payment_allocations collections remained empty for this checkout; old seeded pending June row still appears in parent history separately.
- 2026-06-17T06:15:54: Correction to prior staging note: ledger_payments/payment_allocations are present for Stripe invoice in_1TjHMRRMJDJBjoQzDGafFpf7 when queried by idempotency key rather than enrollment_id. ledger_payments count for stripe-invoice-payment:in_1TjHMRRMJDJBjoQzDGafFpf7 = 1; payment_allocations count for stripe-invoice-allocation:in_1TjHMRRMJDJBjoQzDGafFpf7 = 1; duplicate idempotency-key aggregations returned no rows.
- 2026-06-17T07:03:52: Completed recommendation follow-up on 2026-06-17: implemented Task 10 subscription invoice recovery checkpoints in stripe_invoice_processing and Task 12 legacy payment projection FSM guard; added dedup hardening so store_received short-circuits existing event ids even if staging index is missing. Verification: webhook/dedup focused tests 46 passed; focused Task 9 suites passed (webhook/idempotency/fixture 59 passed, send-invoice/autopay 30 passed, admin/parent interface 44 passed with known Starlette/httpx warning, extra touched tests 33 passed); ruff format --check v2 and ruff check v2 passed; scripts/dev/pre-push-checks.sh passed (E2E skipped because no e2e files changed). Docker SaaS staging after backend rebuild: replayed invoice.paid evt_1TjHMURMJDJBjoQz4RuK3Egr with valid local Stripe signature; route returned stored=false and counts unchanged (ledger_payments=1, payment_allocations=1, legacy_payments=1, existing webhook_events count stayed 2 because one duplicate row had been inserted before hardening). Paid invoice charge proof: POST admin charge-autopay for ledger-in_1TjHMRRMJDJBjoQzDGafFpf7 returned 409 not chargeable status=paid; invoice remained paid balance_due_cents=0 and no payment/allocation counts changed.
- 2026-06-17T07:58:41: Ledger allocation replay repair and monthly orphan-key recovery slices: pytest backend/v2/tests/contract/test_billing_idempotency.py backend/v2/tests/contract/test_mongo_payment_repo.py backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/contract/test_stripe_event_dedup.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py -q => 76 passed. ruff format --check/check touched billing repo/test files => passed.
## Reusable Lessons

- None recorded yet.
