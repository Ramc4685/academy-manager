# app-owned-billing-stripe-processor-only

## Current State

Status: active

## Problem

Verify issue #224: app creates invoices and Stripe only collects payments

## Changed Files

- None recorded yet.

## Log

- 2026-06-21T15:57:21 main/NA: Task ledger created.
- 2026-06-21T15:57:48 main/working: Starting issue #224 before-evidence collection: code-path confirmation, focused baseline tests, and read-only investigation threads A-D
- 2026-06-21T16:04:02 main/working: Starting Slice 1: app-owned monthly invoices for autopay enrollments
- 2026-06-21T16:07:16 main/working: Completed Slice 1 only: active autopay/monthly enrollments now create app-owned monthly LedgerInvoice records through the existing invoice-key path before any Stripe webhook. Remaining issue #224 slices are broader architecture work touching webhook convergence, scheduled reconciliation, new autopay setup, admin visibility, and migration retirement; stop after this safe slice rather than mixing a multi-module rewrite into the existing dirty branch.
- 2026-06-21T16:12:51 main/working: Starting Slice 2 narrow webhook safety: validate app-owned autopay PaymentIntent metadata against the app invoice before recording payment/allocation
- 2026-06-21T16:14:33 main/working: Completed narrow Slice 2 webhook safety: app-owned autopay PaymentIntent success events now quarantine parent_id metadata mismatches before recording ledger payment/allocation.
- 2026-06-21T16:16:35 main/working: Completed failed autopay webhook attempt recording: app-owned payment_intent.payment_failed events now validate invoice metadata, record a failed PaymentAttempt, leave invoice open, and create no payment/allocation.
- 2026-06-21T16:19:01 main/working: Completed direct autopay collection attempt recording: ChargeInvoiceViaAutopay now records PaymentAttempt rows for succeeded, declined, requires_action, and Stripe-error PaymentIntent attempts while preserving invoice-open behavior on failure.
- 2026-06-21T16:20:55 main/working: Starting Slice 4 narrow setup-mode pass: stop new parent autopay setup from creating Stripe subscription Checkout, using Stripe Checkout setup mode for saved payment method collection instead.
- 2026-06-21T16:25:28 main/working: Completed setup-mode autopay slice: new parent autopay setup now uses Stripe Checkout mode=setup with customer_creation=always and source=autopay_setup metadata; checkout-status reconciliation marks setup sessions active without creating Stripe subscriptions while preserving legacy subscription reconciliation.
- 2026-06-21T16:27:43 main/working: RED self-enrollment autopay setup test fails because EnrollChildInSessionType still creates Stripe subscription checkout
- 2026-06-21T16:30:39 main/working: RED scheduled reconciliation tests fail because ReconcileStripePaymentIntents use case is missing
- 2026-06-21T16:35:58 main/working: RED webhook test shows subscription invoice webhook still creates a LedgerInvoice when no app-owned invoice exists
- 2026-06-21T16:37:38 main/working: RED session-type move test shows proration still creates a Stripe invoice via update_subscription_proration
- 2026-06-21T16:41:21 main/working: Implemented app-owned billing slices for issue #224: autopay monthly invoices included; new autopay checkout uses setup mode; webhook and reconciliation converge app invoices idempotently; scheduled PaymentIntent reconciliation added; subscription invoice webhooks now quarantine missing app invoices; session-type proration no longer creates Stripe invoices
## Verification

- No verification recorded yet.
- 2026-06-21T15:59:03: Before focused baseline: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_mongo_payment_repo.py v2/tests/application/test_webhook_handler.py v2/tests/contract/test_billing_idempotency.py v2/tests/unit/test_charge_autopay_use_case.py -q => 75 passed in 21.57s
- 2026-06-21T15:59:03: Before code-path evidence: mongo_payment_repo.py:495-630 generate_monthly_payments skips payment_mode autopay/monthly with subscription_status active/trialing/past_due via skipped_autopay; stripe_gateway.py:67-103 creates Checkout Session mode=subscription; stripe_gateway.py:278-285 creates/finalizes Stripe invoice for subscription proration; handle_webhook_event.py:1143-1235 can create LedgerInvoice from Stripe subscription invoice; main.py:341-374 schedules resumes, webhook inbox drain, coach digests only, with no app-owned monthly billing or Stripe reconciliation job.
- 2026-06-21T16:05:15: RED Slice 1: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_mongo_payment_repo.py::test_generate_monthly_creates_ledger_invoice_for_active_autopay_enrollment_before_webhook v2/tests/contract/test_mongo_payment_repo.py::test_generate_monthly_autopay_invoice_is_idempotent_per_enrollment_period -q => 2 failed as expected because active autopay returned created=0 and skipped_autopay=1
- 2026-06-21T16:06:37: GREEN Slice 1 focused: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_mongo_payment_repo.py -q => 11 passed in 1.36s; pytest v2/tests/contract/test_billing_idempotency.py -q => 10 passed in 1.29s; pytest v2/tests/contract/test_mongo_payment_repo.py v2/tests/application/test_webhook_handler.py v2/tests/contract/test_billing_idempotency.py v2/tests/unit/test_charge_autopay_use_case.py -q => 77 passed in 3.02s; ruff format --check/check touched backend files => passed.
- 2026-06-21T16:06:37: GREEN Slice 1 targeted: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_mongo_payment_repo.py::test_generate_monthly_creates_ledger_invoice_for_active_autopay_enrollment_before_webhook v2/tests/contract/test_mongo_payment_repo.py::test_generate_monthly_autopay_invoice_is_idempotent_per_enrollment_period -q => 2 passed in 2.55s
- 2026-06-21T16:07:16: Backend style after Slice 1: cd backend && source .venv/bin/activate && ruff format --check v2 => 662 files already formatted; ruff check v2 => All checks passed.
- 2026-06-21T16:11:19: Pre-push: scripts/dev/pre-push-checks.sh => backend ruff format/check passed, pytest v2/tests passed, frontend node unit tests passed, pnpm typecheck passed, pnpm lint passed, pnpm e2e failed because http://localhost:3001/login was already used; did not stop the existing process.
- 2026-06-21T16:13:28: RED Slice 2 narrow webhook safety: cd backend && source .venv/bin/activate && pytest v2/tests/application/test_webhook_handler.py::test_autopay_payment_intent_parent_metadata_mismatch_is_quarantined -q => failed as expected; current handler processed the event instead of returning quarantined.
- 2026-06-21T16:14:33: GREEN Slice 2 narrow webhook safety: pytest test_webhook_handler parent-mismatch/missing-parent/retryable allocation tests => 3 passed; pytest v2/tests/application/test_webhook_handler.py v2/tests/contract/test_billing_idempotency.py v2/tests/contract/test_stripe_event_dedup.py -q => 59 passed; focused issue #224 block => 78 passed; ruff format --check v2 and ruff check v2 => passed.
- 2026-06-21T16:15:29: RED failed autopay attempt slice: pytest v2/tests/application/test_webhook_handler.py::test_autopay_payment_intent_failed_records_attempt_without_closing_invoice -q => failed as expected; ledger.payment_attempts was empty while handler only logged the decline.
- 2026-06-21T16:16:35: GREEN failed autopay attempt slice: targeted webhook tests => 3 passed; pytest v2/tests/application/test_webhook_handler.py v2/tests/contract/test_billing_idempotency.py v2/tests/contract/test_stripe_event_dedup.py v2/tests/unit/test_charge_autopay_use_case.py -q => 77 passed; focused issue #224 block => 79 passed; ruff format --check v2 and ruff check v2 => passed.
- 2026-06-21T16:17:48: RED charge-autopay attempt slice: pytest v2/tests/unit/test_charge_autopay_use_case.py::test_happy_path_open_invoice_pi_succeeds ::test_decline_returns_charge_result_false_status_unchanged -q => 2 failed as expected; repo.payment_attempts stayed empty for success and decline.
- 2026-06-21T16:19:01: GREEN charge-autopay attempt slice: targeted success/decline tests => 2 passed; pytest v2/tests/unit/test_charge_autopay_use_case.py -q => 17 passed; focused issue #224 block => 79 passed; ruff format --check v2 and ruff check v2 => passed.
- 2026-06-21T16:21:43: RED setup-mode slice: pytest v2/tests/application/test_parent_billing_portal.py::test_start_autopay_setup_uses_setup_checkout_not_subscription_checkout -q => failed as expected; current result checkout_session_id was cs_test_1 from subscription checkout instead of cs_setup_1.
- 2026-06-21T16:24:11: RED setup-mode checkout-status slice: targeted parent/gateway tests => 3 passed, 1 failed as expected; completed setup checkout without Stripe subscription stayed incomplete instead of marking app autopay active.
- 2026-06-21T16:25:28: GREEN setup-mode slice: targeted parent/gateway tests => 5 passed; pytest v2/tests/application/test_parent_billing_portal.py v2/tests/infrastructure/test_stripe_gateway_request_shape.py -q => 16 passed; expanded focused issue #224 block including parent/gateway setup tests => 95 passed; ruff format --check/check touched setup-mode files => passed; ruff format --check v2 and ruff check v2 => passed.
- 2026-06-21T16:39:14: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_mongo_payment_repo.py v2/tests/application/test_webhook_handler.py v2/tests/contract/test_billing_idempotency.py v2/tests/contract/test_stripe_event_dedup.py v2/tests/unit/test_charge_autopay_use_case.py v2/tests/application/test_parent_billing_portal.py v2/tests/application/test_enroll_child_in_session_type.py v2/tests/application/test_reconcile_stripe_payment_intents.py v2/tests/application/test_session_type_ops.py v2/tests/contract/test_billing_ledger_storage.py v2/tests/contract/test_stripe_webhook_fixture_replay.py v2/tests/unit/test_scheduler_academies.py v2/tests/infrastructure/test_stripe_gateway_request_shape.py -q => 149 passed in 7.20s; ruff format --check v2 && ruff check v2 => 665 files already formatted; All checks passed
- 2026-06-21T16:41:13: scripts/dev/pre-push-checks.sh => backend ruff format/check passed; pytest v2/tests passed; frontend node unit tests passed; pnpm typecheck passed; pnpm lint passed; pnpm e2e failed because http://localhost:3001/login is already in use and Playwright config does not reuse an existing server
## Reusable Lessons

- None recorded yet.
