# feat-billing-billing-setup-stripe-registration-status-invite

PR: #306

## What changed
- Added an admin Billing Setup page for parent registration, saved-card, autopay, and invoice status.
- Added context-aware, retry-safe login/card reminders and membership-aware account detection.
- Added exact-invoice charge confirmation with actual ACH attempt/processing feedback, open-invoice filtering, and replayable audited autopay resumes.
- Added cursor pagination and direct parent action lookup so every matching family remains reachable.

## Deploy notes
No migration, environment variable, or manual deploy step is required. Existing billing audit indexes from migration 0135 provide idempotent audit writes.

## Risk / rollback
Primary risk is incorrect parent provisioning or payment-action targeting. Revert the PR; existing ledger, Stripe idempotency, operation ownership markers, and append-only audit records remain valid.
