# Stripe Python SDK 17 upgrade

PR: #1244

## What changed
The backend Stripe SDK moves from 16.1.0 to 17.0.0. The pinned Stripe API version (2026-10-28.endive) is unchanged, so request and response shapes stay the same. No application code changed.

## Deploy notes
None. No new env vars, webhook endpoint changes or Stripe dashboard steps.

## Risk / rollback
Touches every Stripe call path (checkout, autopay, dunning, Connect, refunds, webhooks) through the SDK only. Watch the first webhooks and one autopay charge after deploy. Roll back by reverting this PR to pin stripe==16.1.0; no data migration.
