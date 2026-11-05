# api-contract-followups

PR: #1149

## What changed
Two more admin money endpoints now declare their response shape, so the frontend contract check covers them. `POST /admin/payments/refund` returns the refund result type the use case already produced, and `GET /admin/billing/invoices/{id}/audit` returns typed audit entries. The audit view copies the billing domain's audit entry, because the API layer may not import the domain directly. A structural test fails if the two drift apart. Both endpoints are added to `frontend/lib/api/billing-contract.ts`. The responses on the wire are unchanged.

`scripts/dev/pre-push-checks.sh` now writes each check's output to its own temp file instead of the shared `/tmp/pre-push-out`, so gates running at the same time in different worktrees no longer overwrite each other's failure output.

Invoice creation (`POST /admin/students/{id}/invoices` and the bill-period route) is still untyped. Typing it means building a view of the full invoice document, and a wrong field there would turn a successful invoice into a 500.

## Deploy notes
Nothing to run. The OpenAPI snapshot and generated frontend types are regenerated.

## Risk / rollback
If a real audit entry ever lacked a required field, the audit endpoint would now return a 500 instead of a partial row. The real lister dumps the domain model, which requires those fields. Roll back by reverting the PR.
