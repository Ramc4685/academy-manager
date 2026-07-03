# stripe connect sample integration

## Current State

Status: active

## Problem

Add a safe sample Stripe Connect integration for account onboarding, product creation, storefront display, and direct-charge Checkout without committing credentials.

## Changed Files

- None recorded yet.

## Log

- 2026-07-03T07:44:30 main/NA: Task ledger created.
- 2026-07-03T07:46:30 main/working: Added isolated Express Stripe Connect sample with account creation, Account Link onboarding, direct status retrieval, connected-account products, storefront listing, and direct-charge Checkout with application fee.
- 2026-07-03T08:10:00 main/working: Added a storefront guard that disables Checkout while the connected account is not charge-enabled and shows Stripe's live onboarding requirements instead of sending customers into a known Checkout failure.
## Verification

- No verification recorded yet.
- 2026-07-03T07:46:30: npm run check in examples/stripe-connect-marketplace passed (node --check server.js). Live Stripe API check skipped because network access is restricted in this session and credentials were not written into the repo.
- 2026-07-03T08:06:00: Live Stripe test-mode smoke passed for balance retrieval, connected account creation with the controller-only create payload, account retrieval, Account Link creation, connected-account product creation/listing via `stripeAccount`, local UI rendering, and storefront rendering. Checkout Session creation is blocked until the connected account completes hosted onboarding/account business-name setup, which is expected for the current account state.
- 2026-07-03T08:10:00: `npm run check` passed after the storefront guard change. Browser verification confirmed the storefront lists the connected-account product and disables the Buy button while Stripe reports `charges_enabled=false`.
## Reusable Lessons

- None recorded yet.
