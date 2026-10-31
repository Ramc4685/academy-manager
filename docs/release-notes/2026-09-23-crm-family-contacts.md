# People CRM Phase 4b: family contacts with opt-in Gets notices, migration 0196

PR: #950

## What changed

- The family record's **Details** tab is now editable. Staff can add a second parent, guardian or other adult as a **family contact** (name, relationship, email, phone), edit or remove it, and edit the family's details (home address, preferred channel, how they heard about us, tags). Forms show errors next to the field and use the admin shell's unsaved-changes guard.
- Each contact has two switches, both **off by default** and never switched on by the system: **Gets notices** and **Gets invoices (opted in)**. A contact is never a user and never gets a login.
- **Gets notices** is wired: a class notice (session announcement, or a campaign to a class) now also reaches each opted-in contact of every family in the class, same academy only, one copy per email (a contact whose email equals the primary parent's gets no second copy). Opted-out contacts and other academies' contacts never receive anything. Suppressed or bounced addresses are refused at send time by the existing suppression gate, exactly as for parents.
- `SelectedRecipientsAudience` gains `include_family_contacts` (default **off**). No existing send sets it yet, so per-family transactional emails (hold, win-back, absence confirmation, roster changes, welcome) and staff alerts are unchanged; turning it on at those parent-directed call sites is a follow-up.
- **Gets invoices** is stored and shown, but invoice emails do not use it yet; its description says so. The invoice recipient wiring is a later change.
- New admin endpoints, all `require_persona("admin")` (coaches and parents get the usual 404): `GET/POST /api/v2/admin/families/{parent_id}/contacts`, `PATCH/DELETE .../contacts/{contact_id}`, `GET/PATCH /api/v2/admin/families/{parent_id}/details`. Another academy's family is a 404; no request body carries an academy (extra fields are refused).
- No change to the family Billing tab, invoices, `main.py`, `composition/admin.py` or `composition/families_crm.py` (the services are composed on first use by the new routes module).

## Deploy notes

- Migration **0196_crm_family_contacts** is applied by the production migrate job (dry run, then the Fly release command) per `docs/runbooks/migrations-rollout.md`; expect it in the dry run's pending list after 0195 (and 0192-0194 if those have not shipped yet). It only creates four indexes on two new, empty collections: `family_contacts` (unique `(academy_id, contact_id)`, lookup `(academy_id, parent_id, created_at)`, and a partial unique `(academy_id, parent_id, email)` filtered on `{email: {$gt: ""}}`) and `family_details` (unique `(academy_id, parent_id)`). Every index leads with `academy_id`; no `$type` filter. No document is modified. Never hand-apply it.
- Until 0196 runs, the new routes still work (Mongo creates the collections on first write) but the per-family email guard and one-details-row guarantee are not enforced; run the migration with the deploy.
- No feature flag, no environment variable, no backfill.

## Risk / rollback

- Only families where staff add a contact AND turn Gets notices on see any change in who is emailed; with no contacts the audience is identical to before (one extra indexed read per class notice).
- Revert the PR to roll back: the routes, tab edits and audience expansion disappear; the two collections and their indexes can stay in place harmlessly.
