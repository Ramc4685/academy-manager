# WI-3 legacy invoice match queue

## Current State

Status: active

## Problem

Implement issue #242 WI-3: human-reviewed match queue for legacy open/partially_paid invoices to Stripe charges (backend port+usecase+routes, admin UI, tests)

## Changed Files

- None recorded yet.

## Log

- 2026-06-23T14:21:15 main/NA: Task ledger created.
- 2026-06-23T14:34:19 main/working: Implemented WI-3: list_charges_for_customer gateway port+impls, list_unmatched_invoices repo, ListLegacyMatchQueue+ConfirmLegacyMatch use cases, admin BFF routes (GET legacy-match-queue, POST legacy-match/confirm), composition+deps wiring, frontend api client+query key+Billing Health 'Legacy Invoice Matches' section with confirm dialog.
## Verification

- No verification recorded yet.
- 2026-06-23T14:34:20: backend: pytest v2/tests -k 'billing/stripe/checkout/reconcile/ledger/legacy/webhook' 410 passed; new test_legacy_match_queue.py + test_admin_billing.py additions 60 passed; ruff check/format clean on all WI-3 files; import-linter adds no new violations (only pre-existing #244). frontend: pnpm typecheck clean, pnpm lint 0 errors.
## Reusable Lessons

- None recorded yet.
