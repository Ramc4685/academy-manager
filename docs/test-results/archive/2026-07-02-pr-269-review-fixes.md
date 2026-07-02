# PR 269 review fixes

## Current State

Status: active

## Problem

Resolve valid PR 269 review comments for autopay/Connect/dunning billing stack before merge

## Changed Files

- None recorded yet.

## Log

- 2026-07-02T12:32:14 main/NA: Task ledger created.
- 2026-07-02T12:42:10 main/working: Applied review fixes for migrations, Connect onboarding/webhooks, Stripe search shape, dunning reclaim, enrollment status race guard, ACH discount rollback, proxy-aware IP capture, and cleanup script id validation.
## Verification

- No verification recorded yet.
- 2026-07-02T12:43:14: Focused backend verification passed: pytest for webhook Connect tenant/status projection, reconciliation, migrations, dunning state repo, enrollment status repo, Stripe request shape, parent checkout IP helper, AddInvoiceLine, ChargeInvoiceViaAutopay, cleanup script (149 passed, 1 existing Starlette TestClient deprecation warning). Ruff format --check backend/v2 scripts/dev/cleanup_stale_tuition_subscriptions.py and ruff check backend/v2 scripts/dev/cleanup_stale_tuition_subscriptions.py passed.
- 2026-07-02T12:43:55: Pre-push verification passed via scripts/dev/pre-push-checks.sh: backend ruff format/check, backend pytest v2/tests, frontend node unit tests, pnpm typecheck, pnpm lint. E2E skipped by script because no e2e/ files changed.
## Reusable Lessons

- None recorded yet.
