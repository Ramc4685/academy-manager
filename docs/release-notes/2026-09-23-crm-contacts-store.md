# crm_contacts lead store: model, repository, CreateContact use case, migration 0192

PR: #0000

## What changed

- New bounded context `backend/v2/contexts/crm` with the `crm_contacts` lead record shared by the People CRM and the public tenant page's anonymous trial-request form: `CrmContact` (name, email, phone digits, source, child name and age, requested class, `pipeline_status` as the lifecycle stage, pipeline override, referrer, converted parent, linked family and user ids, consent flags, created_by, dedupe key, timestamps), `MongoCrmContactRepository` (tenant-scoped) and the `CreateContact` use case.
- `CreateContact` validates and normalises input (email lower-cased, phone to digits, size caps, source `website` / `whatsapp_or_phone` / `referral` / `other`, new contacts start as `lead` or `trial`) and is idempotent for `website` rows: a repeat of the same public inquiry returns the existing row with `created=False`, decided by a unique `(academy_id, dedupe_key)` index, so concurrent double submits produce one row. Staff quick-add sources get no dedupe key and always insert, so two people sharing a household phone or email are never merged.
- Migration `0192_crm_contacts` creates four indexes, all led by `academy_id`; the dedupe index is partial on `{"dedupe_key": {"$gt": ""}}`. No document validator yet.
- `crm_contacts` is registered in `TENANT_OWNED_COLLECTIONS`, and the dedupe lookup is added to the real-mongod planner test. New unit and cross-academy contract tests.
- Consumer contract in `backend/v2/contexts/crm/README.md`; the People CRM engineering spec §5 points to it.
- No route, no composition wiring, no frontend change. Nothing writes the collection until a consumer (the public trial-request endpoint or the CRM quick add) ships.

## Deploy notes

- Migration 0192 is applied by the production migrate step (dry run, then the Fly release command) per `docs/runbooks/migrations-rollout.md`; expect `pending_before count=1 versions=['0192_crm_contacts']` in the dry run. It only creates indexes on a new, empty collection, so it is fast and safe to apply before or after the code.
- No feature flag, no environment variable, no backfill.

## Risk / rollback

- Low: new collection and new code with no caller. No existing read or write path changes.
- Rollback: revert the PR. If 0192 was applied, the empty `crm_contacts` collection and its indexes can stay (harmless) or be dropped with `db.crm_contacts.drop()` and `db.v2_migrations.deleteOne({version: "0192_crm_contacts"})`.
