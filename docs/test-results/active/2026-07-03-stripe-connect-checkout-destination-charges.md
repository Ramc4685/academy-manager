# Stripe Connect checkout destination charges

## Current State

Status: active

## Problem

Hosted invoice Checkout and pay-balance Checkout were creating platform charges instead of destination charges for charge-ready academy connected accounts.

## Changed Files

- None recorded yet.

## Log

- 2026-07-03T11:45:50 main/NA: Task ledger created.
- 2026-07-03T11:46:17 main/working: Continued interrupted Stripe Connect checkout-routing fix. Hosted invoice checkout now accepts connected_account_id and emits Checkout payment_intent_data destination-charge fields. Admin send invoice and parent single-invoice retry wire MongoConnectedAccountRepository into SendInvoice, which refuses to mint platform-charge pay links when the account is missing/not charge-ready. Parent pay-balance now requires a ready connected account and passes its Stripe account id to checkout.
- 2026-07-03T11:57:35 main/working: Addressed security-review findings: SendInvoice now refuses checkout when Stripe is configured without a connected-account repository, logs Checkout session id instead of full URL, admin tests use a ready connected account, and parent single-invoice/balance composition tests cover ready and missing-account behavior. Added pay-balance provider-error guard to return controlled unavailable response instead of raw 500 when Stripe rejects destination charge setup.
## Verification

- No verification recorded yet.
- 2026-07-03T11:46:17: PYTHONPATH=. backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_send_invoice_use_case.py backend/v2/tests/unit/test_parent_composition.py backend/v2/tests/contract/test_stripe_gateway_request_shape.py backend/v2/tests/interface/test_admin_billing.py::test_send_invoice_returns_checkout_url_when_stripe_configured backend/v2/tests/interface/test_admin_billing.py::test_send_invoice_with_email_marks_sent_and_passes_checkout_url backend/v2/tests/interface/test_parent_invoice_routes.py -q => 41 passed, 1 StarletteDeprecationWarning. backend/.venv/bin/python -m ruff check touched billing/composition/test files => All checks passed.
- 2026-07-03T11:57:35: Security reviewer reported P2 fail-open optional connected_accounts and P3 full checkout URL logging. Both fixed locally. Focused tests rerun: PYTHONPATH=. backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_send_invoice_use_case.py backend/v2/tests/unit/test_parent_composition.py backend/v2/tests/contract/test_stripe_gateway_request_shape.py -q => 34 passed. Interface focused tests => 10 passed, 1 StarletteDeprecationWarning. Ruff touched files => All checks passed.
- 2026-07-03T11:57:35: Docker SaaS staging: stripe listen forwarder ran to http://127.0.0.1:8001/api/v2/parent/webhooks/stripe and webhooks returned 200. After rebuilding backend, parent pay-balance for BLNO attempted destination-charge Checkout and Stripe rejected the connected account for missing transfer/stripe_transfers capability; API now returns HTTP 409 {detail: balance payment unavailable} instead of 500. A successful paid destination-charge smoke remains blocked by the sandbox connected account capability state.
- 2026-07-03T12:01:22: Current continuation verification: PYTHONPATH=. backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_send_invoice_use_case.py backend/v2/tests/unit/test_parent_composition.py backend/v2/tests/contract/test_stripe_gateway_request_shape.py backend/v2/tests/interface/test_admin_billing.py::test_send_invoice_returns_checkout_url_when_stripe_configured backend/v2/tests/interface/test_admin_billing.py::test_send_invoice_with_email_marks_sent_and_passes_checkout_url backend/v2/tests/interface/test_parent_invoice_routes.py -q => 44 passed, 1 StarletteDeprecationWarning. backend/.venv/bin/python -m ruff check touched backend billing/composition/test files => All checks passed.
- 2026-07-03T12:02:58: Pre-push verification: scripts/dev/pre-push-checks.sh => backend ruff format/check passed, pytest v2/tests passed, frontend node unit tests passed, pnpm typecheck passed, pnpm lint passed; E2E skipped by script because no e2e files changed.
- 2026-07-03T12:07:05: Connect webhook secret support verification: PYTHONPATH=. backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_settings.py backend/v2/tests/infrastructure/test_stripe_gateway_request_shape.py backend/v2/tests/unit/test_send_invoice_use_case.py backend/v2/tests/unit/test_parent_composition.py backend/v2/tests/contract/test_stripe_gateway_request_shape.py backend/v2/tests/interface/test_admin_billing.py::test_send_invoice_returns_checkout_url_when_stripe_configured backend/v2/tests/interface/test_admin_billing.py::test_send_invoice_with_email_marks_sent_and_passes_checkout_url backend/v2/tests/interface/test_parent_invoice_routes.py -q => 75 passed, 1 StarletteDeprecationWarning. Ruff touched settings/gateway/main/billing/composition/test files => All checks passed.
- 2026-07-03T12:08:50: Second pre-push verification after Connect webhook secret support: scripts/dev/pre-push-checks.sh => backend ruff format/check passed, pytest v2/tests passed, frontend node unit tests passed, pnpm typecheck passed, pnpm lint passed; E2E skipped by script because no e2e files changed.
## Reusable Lessons

- None recorded yet.
