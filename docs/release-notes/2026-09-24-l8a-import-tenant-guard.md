# CSV family import refuses an unset or mismatched tenant

PR: #963

## What changed

- This is a follow-up to #962. The CSV family import routes (`POST /api/v2/admin/imports/families/preview` and `/commit`) return 503 when the request has no tenant context. Before this change they fell back to the academy in the login claims. They return 404 when the tenant context and the claims name different academies.
- Every stored import batch now records its academy. Committing a batch that belongs to another academy is refused as not found, even if the store's own tenant scoping failed.

## Deploy notes

- No new migration. Migrations `0199_import_batches` and `0200_tenant_fee_model_and_agreement` came in with #962 and still run only through the production migrate job.
- No new owner step. The owner steps from #962 still apply: supply the platform agreement text and version, then record the live academy's acceptance.

## Risk / rollback

- Low risk. Normal admin requests always have a tenant context that matches their claims, so they behave as before. Only malformed or cross-tenant requests are now refused.
- Rollback: revert this PR. No data or index changes are involved.
