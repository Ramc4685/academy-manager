# autopay setup rehome default payment method

## Current State

Status: active

## Problem

Re-home Stripe setup-mode autopay completion so it sets the customer default payment method, marks app-owned autopay active, and creates no legacy subscription rows.

## Changed Files

- None recorded yet.

## Log

- 2026-06-30T16:33:39 main/NA: Task ledger created.
- 2026-06-30T16:50:27 main/working: Implemented setup-mode autopay re-home on branch feat/autopay-setup-rehome-default-pm: setup Checkout now stamps SetupIntent metadata, setup completion sets Stripe Customer default PM/metadata, persists parent billing customer PM projection, marks enrollment autopay active, handles checkout.session.completed/setup_intent.succeeded, and no longer writes setup rows to subscriptions.
## Verification

- No verification recorded yet.
- 2026-06-30T16:50:27: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && ruff format --check backend/v2 && ruff check backend/v2 => 709 files already formatted; All checks passed.
- 2026-06-30T16:50:27: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && pytest backend/v2/tests/application/test_parent_billing_portal.py backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/infrastructure/test_stripe_gateway_request_shape.py -q => 66 passed.
- 2026-06-30T16:50:27: cd backend && source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && pytest v2/tests -q => 1740 passed, 5 warnings.
## Reusable Lessons

- None recorded yet.
