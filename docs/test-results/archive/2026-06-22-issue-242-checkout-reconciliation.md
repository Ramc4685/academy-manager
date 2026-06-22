# issue 242 checkout reconciliation

## Current State

Status: active

## Problem

Fix GitHub issue #242: checkout payments must close app invoices via webhook and reconcile from PaymentIntent metadata when webhooks are missed; legacy unmatched payments need review support.

## Changed Files

- None recorded yet.

## Log

- 2026-06-22T17:36:40 main/NA: Task ledger created.
- 2026-06-22T17:36:55 main/working: Started #242 implementation. Current behavior: single invoice Checkout relies on checkout.session.completed; PaymentIntent metadata is missing so reconciler can scan 0; pay-balance sends invoice_ids and is not routed to ledger allocation. Plan: TDD for balance allocation, PaymentIntent metadata, missed-webhook reconciliation, and legacy review support.
- 2026-06-22T17:48:20 main/working: Implemented checkout PaymentIntent metadata propagation, safe checkout PI webhook no-op, shared balance allocation for checkout webhooks/reconciliation, manual review candidates, and zero-scan reconciliation notes. Running focused verification.
- 2026-06-22T17:49:23 main/working: Ruff format check required formatting the new checkout allocation helper; formatting and rerunning touched checks.
## Verification

- No verification recorded yet.
- 2026-06-22T17:48:56: Focused/broader backend verification passed: pytest v2/tests/application/test_reconcile_stripe_payment_intents.py v2/tests/application/test_webhook_handler.py v2/tests/infrastructure/test_stripe_gateway_request_shape.py v2/tests/interface/test_admin_billing.py v2/tests/unit/test_admin_composition_tenancy.py -q => 131 passed, 1 warning. Backend ruff check on touched billing/admin files passed. Frontend pnpm typecheck passed.
- 2026-06-22T17:49:17: Additional verification passed: frontend pnpm lint completed with 0 errors and 5 pre-existing warnings outside touched files.
- 2026-06-22T17:49:53: Post-format verification passed: ruff format --check and ruff check on touched backend files passed; backend pytest set still 131 passed, 1 warning.
## Reusable Lessons

- None recorded yet.
