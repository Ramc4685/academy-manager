# feat-billing-billing-setup-stripe-registration-status-invite

PR: #306

## What changed
- Added an admin Billing Setup page for parent registration, saved-card, autopay, and invoice status.
- Added context-aware login/card reminders, exact-invoice charge confirmation, and audited paused-to-active autopay resumes.
- Added cursor pagination so every matching family remains reachable.

## Deploy notes
No migration, environment variable, or manual deploy step is required. Existing billing audit indexes from migration 0135 provide idempotent audit writes.

## Risk / rollback
Primary risk is incorrect parent provisioning or payment-action targeting. Revert the PR; existing ledger, Stripe idempotency, and append-only audit records remain valid.
