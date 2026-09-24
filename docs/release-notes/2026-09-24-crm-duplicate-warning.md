# People CRM Phase 4c: duplicate warning on Add user / Add parent / Add contact, migration 0198

PR: #TBD

## What changed

- When staff leave the email or phone field of the **Add user / Add parent** dialog (Users directory) or the **Add contact** form (family record, Details tab), the form now checks whether the person looks like someone the academy already has and shows a non-blocking notice: "Possible match: <name> - open", in a polite live region. Save still works; nothing is merged or refused. There is no staff Add inquiry form yet; the same component is ready for it.
- New endpoint `POST /api/v2/admin/people/duplicate-check` `{email?, phone?, name?}` (admin persona only; coaches and parents get the usual 404) returns up to 5 matches `{kind, display_name, email_masked, phone_masked, link, matched_on}` from this academy only: families (the family index), family contacts, staff users with an active membership here, and inquiries (`crm_contacts`). Email matches case-insensitively, phone in any punctuation with or without the +1 country code, name only exactly. Contact details come back masked. Rate-limited to 60 per minute per client.
- The two-tenant isolation test covers the new route, and now also knows the `contact_id` path parameter added by #950 (it failed on main without it).

## Deploy notes

- Migration **0198_crm_duplicate_lookup_indexes** is applied by the production migrate job (dry run, then the Fly release command) per `docs/runbooks/migrations-rollout.md`; expect it in the dry-run pending list after 0196 and any 0197 (and 0192-0195 if those have not shipped yet). It only creates four non-unique partial indexes: `crm_contacts (academy_id, email)` and `(academy_id, phone_digits)`, `family_contacts (academy_id, email)` and `(academy_id, phone_digits)`, each filtered on `{field: {$gt: ""}}`. Every index leads with `academy_id`; no `$type` filter; no document is modified. Both collections are small. Never hand-apply it.
- Until 0198 runs, the check still works but its inquiry and family-contact lookups scan the academy's rows of those collections.
- No feature flag, no environment variable, no backfill.

## Risk / rollback

- Read-only: the endpoint writes nothing and the forms never wait on it to save. If the check fails the forms show no notice and work as before.
- Revert the PR to roll back; the four indexes can stay in place harmlessly.
