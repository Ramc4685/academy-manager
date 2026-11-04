# Tenant data export and purge (roadmap L9d)

What exists in the app, and the hand-run, owner-confirmed procedure for the
part that deliberately does not.

## What the app does

Both endpoints are **platform admin only** (anyone else gets `404`) and each
call writes one `platform_audit_events` row. If the audit row cannot be
written the call fails: tenant data never leaves without a trail.

| Endpoint | What it does |
| --- | --- |
| `POST /api/v2/platform/tenants/{academy_id}/data-export` with `{"reason": "..."}` | Returns a zip of every tenant-scoped collection filtered by `academy_id`. Audit action `tenant.data_exported` (reason, archive SHA-256, byte size, per-collection counts). Allowed for any tenant status. |
| `POST /api/v2/platform/tenants/{academy_id}/purge-dry-run` | Counts per collection what a purge would delete and what it would keep. **Deletes nothing.** Refused with `409 Platform.TenantInvalidTransition` unless the tenant is `cancelled`. Audit action `tenant.purge_dry_run` (counts and `confirm_token`, `executed: false`). |

The platform tenant page (`/platform/tenants/{academyId}`) has a "Data export
and purge" card for platform admins with both actions.

There is **no purge execution endpoint.** That is intentional.

### Archive layout

```
manifest.json                   format_version, academy_id, tenant_status, generated_at,
                                generated_by, reason, per-collection counts,
                                total_documents, sha256 of every file
collections/<collection>.jsonl  one document per line, MongoDB relaxed Extended JSON
```

Relaxed Extended JSON keeps ObjectIds, dates and decimals typed, so
`mongoimport --mode=insert` (or `bson.json_util.loads`) restores the rows.
Only collections with at least one row for the academy get a file.

The zip is built in memory. That is fine for today's academies (thousands of
rows); if an academy grows past a few hundred MB of data, move the export to
a background job that writes to object storage before using it.

### Which collections are covered

Collections are **discovered from the live database** (`listCollections`), not
from a hand-kept list, so a collection added later is exported without
anyone registering it. Every document with the tenant's `academy_id` is
exported, except from the platform-owned collections listed in
`PLATFORM_INTERNAL_COLLECTIONS` in
`backend/v2/contexts/platform/application/use_cases/tenant_data_offboarding.py`
(platform audit trail, governance requests, support access, the platform's
own subscription billing). Those record what the platform did about the
academy, not the academy's data.

A purge keeps the platform-owned collections plus `RETAINED_ON_PURGE`:
`academies` (the tenant record stays as a cancelled tombstone so the slug and
domain are not silently reused) and `users` (a login can belong to several
academies).

`backend/v2/tests/unit/test_tenant_data_offboarding.py` fails if any
collection in the tenant-scope guard's `TENANT_OWNED_COLLECTIONS` is ever put
in either exclusion list, and the real-mongod contract test
`backend/v2/tests/contract/test_tenant_data_offboarding.py` seeds every one of
them for two academies and proves the export of one carries all of its rows
and none of the other's.

Not in the archive: Firebase Auth accounts (outside Mongo), Stripe objects
(held by Stripe on the academy's connected account), and email provider logs.

## Owner-confirmed purge procedure (manual)

A purge is irreversible. Only the owner can authorise it, per tenant, in
writing. The agent or operator never runs it on their own initiative.

1. **Tenant is cancelled.** Cancel it on the platform tenant page (or
   `POST /platform/tenants/{academy_id}/cancel`) with a reason. Wait out any
   notice period the platform agreement promises.
2. **Export first.** Run the data export, check `manifest.json` counts, and
   store the zip where the owner decides (the academy may be owed a copy).
   Record the archive SHA-256 from the audit row.
3. **Retention check.** Invoices, payments and ledger rows can carry legal
   retention duties. The owner decides whether financial collections are
   purged now or kept until the retention period ends. Write the decision
   down with the collection list.
4. **Dry run.** Run the purge preview. Send the owner the `would_delete`
   counts, the `would_retain` list and the `confirm_token`.
5. **Owner confirms** the counts and the token, in writing.
6. **Execute by hand**, against production, from a one-off script reviewed
   in a PR (never from a laptop shell history):
   * re-run the dry run immediately before deleting and stop if the
     `confirm_token` differs from the one the owner confirmed (any write
     since the preview changes the token);
   * for each collection in `would_delete`, `delete_many({"academy_id": id})`
     and check the deleted count equals the previewed count;
   * write a `platform_audit_events` row with action `tenant.purged`, the
     token, the per-collection deleted counts and the owner's confirmation
     reference.
7. **Outside Mongo.** Delete or disable the academy's Firebase users that
   have no other academy membership, detach the tenant's domain in DNS/Fly
   certificates, and leave the Stripe connected account to the academy.
8. Tell the owner it is done, with the audit row id.

If any step disagrees with its expected count, stop and ask the owner.
