# CSV family import, fee model and agreement acceptance, tenant export and purge dry run

PR: #962

## What changed

- **CSV family import (L8a, L8b):** admins can import families and students from a CSV file in a new "Import from CSV" panel on the Families page. "Check file" runs a dry run (`POST /api/v2/admin/imports/families/preview`) that reports results per row and writes nothing. Import (`POST /api/v2/admin/imports/families/commit`) inserts only when no row has an error. A commit is idempotent by import batch, so re-uploading the same file changes nothing. Leading formula characters are stripped. The L1c duplicate finder matches existing families by email and phone. New families are roster families: nobody is emailed and no login is created. The duplicate matcher now also compares `parent_email`.
- **Fee model and platform agreement (L9c):** the tenant record gains `fee_model` (`flat_monthly`) and the platform agreement version, acceptance time and signatory. Platform admins record an acceptance on the platform tenant page. Activating a provisioning tenant now requires a recorded acceptance. Reactivating a tenant is unchanged.
- **Tenant data export and purge dry run (L9d):** platform admins can download a zip of every tenant-scoped collection for one academy, with a manifest of counts and checksums. For cancelled tenants they can preview what a purge would delete. Both actions write platform audit rows. Nothing deletes data, and there is no purge execution route.

## Deploy notes

- Migration `0199_import_batches` creates the `import_batches` indexes: unique `(academy_id, import_batch_id)` and `(academy_id, created_at desc)`.
- Migration `0200_tenant_fee_model_and_agreement` backfills `fee_model = flat_monthly` and null agreement fields on academies that do not have them. It does not record an acceptance.
- Both migrations run only through the production migrate job. Nothing is applied on boot.
- Owner step: supply the platform agreement text and version (`docs/platform/platform-agreement.md` is a DRAFT placeholder), then record the live academy's acceptance. The live academy is already active and keeps working without it. Only activating a new tenant is blocked.
- Owner step: an actual tenant purge is a manual procedure the owner confirms, documented in `docs/runbooks/tenant-export-and-purge.md`.

## Risk / rollback

- Risk is low for the live academy. The import is admin-only and opt-in, with a dry run first. The agreement guard applies only to provisioning-to-active activation. Export and purge preview are read-only and platform-admin only.
- The family index now reads `parent_phone` and matches on `parent_email`. The Add family duplicate warning can therefore surface more matches.
- Rollback: revert the PR. Migration 0199 only adds indexes on a new collection, and migration 0200 only adds fields. Both can stay in place after a revert without affecting older code.
