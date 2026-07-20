# Combined student-balance invoice links

PR: #303

## What changed
Admin-sent invoice emails now bundle all eligible open invoices for the same
student, parent, and currency into one Stripe pay link. The email shows the
combined balance, while existing webhook and reconciliation logic allocates the
payment back across the included invoices idempotently.

## Deploy notes
No migration, environment variable, or manual deployment step is required.

## Risk / rollback
The primary risk is including the wrong invoice in a combined checkout or
showing an email amount that differs from Stripe. Revert PR #303 to restore
single-invoice admin links. Checkout sessions already created by this version
remain valid and must not be deleted or re-created manually.
