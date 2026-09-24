# `crm` context: the `crm_contacts` lead store

`crm_contacts` is the **one** store for people the academy hears from before
an account exists. Two consumers write it, and both must go through
`CreateContact`:

- the **public tenant page** trial-request form (`POST /api/v2/public/trial-requests`,
  anonymous, source `website`), and
- the **People CRM** quick add and Pipeline board (staff sources).

Sources of truth: `docs/design/people-crm/engineering-spec.md` §5 and §6, and
the public tenant page brief (`docs/design/public-tenant-page/brief.md` §5
"Trial request", §6 piece F). This README is the contract; if it and the
code disagree, the tests in `backend/v2/tests/unit/test_crm_create_contact.py`
decide.

This context ships the record, the repository, the use case and migration
`0192_crm_contacts`. The contact store ships no route and no composition
wiring (the read-only family index below has its own). Each
consumer adds its own.

## Layout

| File | What it is |
|---|---|
| `domain/models.py` | `CrmContact`, `ContactConsent`, `PipelineOverride`, the `ContactSource` and `PipelineStatus` vocabularies, size caps, normalisers, `compute_dedupe_key` |
| `domain/errors.py` | `InvalidContact` (422, `Crm.InvalidContact`, `details["field"]` names the field) |
| `application/ports.py` | `CrmContactRepository` protocol |
| `application/use_cases/create_contact.py` | `CreateContact`, `CreateContactCommand`, `CreateContactResult` |
| `infrastructure/mongo_crm_contact_repo.py` | `MongoCrmContactRepository(TenantScopedRepository)` |
| `backend/v2/migrations/0192_crm_contacts.py` | the indexes |
| `application/people_reports.py` | People reports (L5a): money owed by age band (billing's money rule asked at today, today-30, today-60) and inquiry conversion by source; read-only, routes in `interfaces/admin/people_reports_routes.py` |

## The record

Collection `crm_contacts`, one document per inquiry.

| Field | Type | Written by | Meaning |
|---|---|---|---|
| `contact_id` | str (ULID) | CreateContact | Primary id. Unique per academy. |
| `academy_id` | str | repository | Always the tenant scope's academy (`current_academy_id()`), never caller input. |
| `name` | str, 1-120 | both | The person who inquired (parent or adult player). Whitespace collapsed. |
| `email` | str or null, <= 254 | both | Lower-cased. Email or phone is required. |
| `phone_digits` | str or null, 7-15 digits | both | Digits only; `(555) 010-2030` becomes `5550102030`. |
| `source` | `ContactSource` | both | See below. |
| `child_name` | str or null, <= 120 | CRM only | The public form must not collect it (brief §5). |
| `child_age` | str or null, <= 20 | both | Free text as typed ("9", "5 to 8"). Not a number on purpose. |
| `requested_session_id` | str or null, <= 64 | both | The class asked about, when one was picked. Not checked against `sessions` here; the consumer validates it if it cares. |
| `message` | str or null, <= 1000 | both | Optional free-text note left with the inquiry (the public form's "anything the coach should know"). Plain text, line breaks kept; never rendered as HTML. Not part of the dedupe key. |
| `pipeline_status` | `PipelineStatus` | both | **The lifecycle stage** of this lead. |
| `pipeline_override` | `{column, set_by, set_at}` or null | CRM only | A board move with no system write behind it (spec §3.4). Not set by CreateContact. |
| `referrer_parent_id` | str or null | CRM only | Who referred them. Only allowed when `source == "referral"`. |
| `converted_parent_id` | str or null | conversion flow | Parent user created or linked on "Convert to family". |
| `linked_family_id` | str or null | conversion flow | The family record this contact belongs to (the id used by `/admin/families/{id}`). |
| `linked_user_id` | str or null | conversion flow | The user account this contact became, when that is not the parent (for example an adult player). |
| `consent` | `ContactConsent` | both | `{contact_about_request: bool, marketing: bool, captured_at: datetime, privacy_notice_url: str or null}`. `captured_at` is stamped when not given. `marketing` defaults to false; never send marketing without it. |
| `created_by` | str or null | CRM only | Staff user id. Always null for `website` (anonymous). |
| `dedupe_key` | str (64 hex) or absent | CreateContact | Idempotency key, see below. Set only for `website` rows; absent on staff quick-add rows. |
| `created_at`, `updated_at` | UTC datetime (ms) | CreateContact | |

The conversion fields (`converted_parent_id`, `linked_family_id`,
`linked_user_id`) and `pipeline_override` exist in the model and are read back
by the repository, but no use case in this PR writes them.

### `ContactSource`

| Value | Who writes it |
|---|---|
| `website` | Only the public trial-request endpoint. Anonymous: `created_by` and `referrer_parent_id` must be null. |
| `whatsapp_or_phone` | Staff quick add. |
| `referral` | Staff quick add; may carry `referrer_parent_id`. |
| `other` | Staff quick add; anything else. |

### `PipelineStatus` (the stage)

`lead` (an inquiry, no trial yet), `trial` (a trial was asked for or booked),
`enrolled` (converted). `CreateContact` accepts only `lead` or `trial`;
`enrolled` is reached by the conversion flow. The public form uses `trial` for
"book a free trial" and `lead` for "tell me when classes open" and the
waitlist variant (brief §5).

## Indexes (migration 0192)

| Name | Keys | Options |
|---|---|---|
| `crm_contacts_academy_contact_unique` | `(academy_id, contact_id)` | unique |
| `crm_contacts_academy_dedupe_unique` | `(academy_id, dedupe_key)` | unique, partial `{"dedupe_key": {"$gt": ""}}` |
| `crm_contacts_academy_pipeline_created` | `(academy_id, pipeline_status, created_at desc)` | |
| `crm_contacts_academy_created` | `(academy_id, created_at desc)` | |

Every index leads with `academy_id`. The partial filter is the planner-usable
`$gt: ""` shape (#878), and `test_partial_index_planner_usability` checks the
dedupe lookup against a real `mongod`. No `$jsonSchema` validator yet (the
shape is still shared between two consumers; see the migration docstring).
Production applies 0192 through the deploy pipeline's migrate step
(`docs/runbooks/migrations-rollout.md`), not by hand.

## Idempotency and dedupe

Only `website` rows are deduped. Staff quick-add sources (`whatsapp_or_phone`,
`referral`, `other`) get no `dedupe_key` (the field is absent, so the partial
unique index skips them) and every call inserts a new row. The key ignores the
person's own name, so applying it to staff entries would silently merge two
different people who share a household phone or email. Staff double-submit
protection belongs in the quick-add form (disable the button while saving).

For `website` rows:

`dedupe_key = sha256("\x1f".join([source, email, phone_digits, child_name, child_age, requested_session_id]))`
over the **normalised** values: email lower-cased and trimmed, phone reduced to
digits, child name and age whitespace-collapsed and case-folded, a missing
value as `""`. The person's own `name` is not part of it, so a retry with a
corrected spelling still dedupes. Use `compute_dedupe_key` if you need the
value; never re-implement it.

Semantics:

- Same inquiry again (double tap, network retry, the same person asking about
  the same class for the same child age a week later) in the same academy:
  **no second row.** `CreateContact` returns the existing row with
  `created=False`. It does not raise and does not update the existing row.
- A different class, child age, child name, email or phone is a new
  lead (a second child is a second row).
- The same inquiry in another academy is a separate row; dedupe is per
  academy.
- Race-safe: the unique `(academy_id, dedupe_key)` index decides. Concurrent
  identical submissions produce one row, and every caller gets that row back
  (checked against a real `mongod`). There is no read-then-insert.

There is no fuzzy merge (the same phone under a different source is a new
row). The CRM's duplicate warning ("Open existing family") is a read-side
feature for later.

## How to use it

```python
from backend.v2.contexts.crm.application.use_cases.create_contact import (
    CreateContact,
    CreateContactCommand,
)
from backend.v2.contexts.crm.domain.errors import InvalidContact
from backend.v2.contexts.crm.domain.models import ContactConsent
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.shared.tenancy import tenant_scope  # or the request's scope


def build_create_contact(db) -> CreateContact:  # in YOUR composition module
    return CreateContact(MongoCrmContactRepository(db))  # clock/new_id injectable for tests


# Inside a request whose tenant scope is already set:
result = await create_contact.execute(
    CreateContactCommand(
        name=body.name,
        source="website",
        email=body.email,
        phone=body.phone,  # any punctuation; digits are kept
        child_age=body.player_age,
        requested_session_id=body.class_id,  # optional
        pipeline_status="trial",  # or "lead" for the notify-me variants
        consent=ContactConsent(
            contact_about_request=True,
            marketing=body.marketing_opt_in,  # default False
            privacy_notice_url=privacy_url,
        ),
    )
)
result.contact  # CrmContact (new or existing)
result.created  # False on a repeat
```

`InvalidContact` is a `DomainError`, so the registered handler turns it into
a 422 with `code = "Crm.InvalidContact"` and `details.field`. Validation
rules: name required, email or phone required, email must have exactly one
`@` and no spaces, phone 7-15 digits, the size caps above, source and stage
from the vocabularies, `referrer_parent_id` only for `referral`, and a
`website` contact has no `created_by` or `referrer_parent_id`.

### Tenant scope for the anonymous endpoint

The repository reads the academy from the tenant ContextVar and raises when
none is set. An anonymous route must:

1. take the academy **only** from the host, via the resolver middleware
   (`request.state.resolved_academy_id`, as `interfaces/registration_routes.py`
   does);
2. return the same 404 when there is no resolved academy, and never fall back
   to `default_academy_id`;
3. run the call inside `tenant_scope(resolved_academy_id)` (or wherever the
   middleware already set it).

The endpoint takes no academy, tenant or slug parameter.

## What a consumer must NOT do

- **Do not create a second collection or a second record shape** (no
  `public_trial_requests`, no `leads`). New fields are added here, to
  `CrmContact`, the repository mapping and this README, in the same PR.
- **Do not write `crm_contacts` directly** (`db["crm_contacts"]...`). It is
  registered in `TENANT_OWNED_COLLECTIONS`, so the structural test fails raw
  access. Add a method to `MongoCrmContactRepository` instead.
- **Do not build your own dedupe** (pre-checking by email, catching
  `DuplicateKeyError` yourself, adding another unique index). `created=False`
  already tells you it was a repeat.
- **Do not reveal `created`** to an anonymous caller. The public response must
  be identical for new and repeated submissions so the form cannot be used to
  find out who has already inquired (brief §5). Use `created` server-side
  only, for example to skip a second academy notification email for a double
  tap.
- **Do not pass `academy_id`**, and do not trust one from the request body.
- **Do not send `child_name` from the public form**, or `created_by` /
  `referrer_parent_id` for `website`.
- **Do not wire into `backend/v2/composition/admin.py`**: it is at its
  4,500-line cap. Add a new composition module (for example
  `composition/public_trial_requests.py` or `composition/crm.py`).
- **Do not use the parent trial-requests queue** (`trial_requests`,
  enrollment context) for public leads. That queue is for signed-in parents.
- Rate limiting, the honeypot, size caps on the raw request body and the
  acknowledgement and academy emails belong to the endpoint, not here.

## The public trial-request endpoint (Lane B4)

`POST /api/v2/public/trial-requests` (`interfaces/public/trial_request_routes.py`,
wired by `composition/public_trial_requests.py`) is the `website` writer. It
takes the academy from the host only, refuses with the unknown-host 404 while
the page is unpublished, answers `409 Public.TrialsClosed` when trials are
switched off, resolves the optional class from its opaque `public_id` against
the academy's **published** classes only, and returns one acknowledgement body
for new, repeated and honeypot submissions. `created` is used only after the
response, to email the academy's owners once per new row.


## Tests

- `backend/v2/tests/unit/test_crm_create_contact.py`: behaviour, validation,
  dedupe, against the real repository and the 0192 indexes (mongomock).
- `backend/v2/tests/unit/test_0192_crm_contacts.py`: index shapes.
- `backend/v2/tests/contract/test_crm_contacts_are_academy_scoped.py`:
  cross-academy reads see nothing; writes stamp the tenant.
- `backend/v2/tests/contract/test_partial_index_planner_usability.py`: the
  dedupe lookup is served by its index on a real `mongod`.

## The family index (People CRM Phase 2, backend)

Read-only. Backs `GET /api/v2/admin/families` and
`GET /api/v2/admin/families/summary` (both `require_persona("admin")`;
`tests/structural/test_crm_admin_persona_gate.py` pins every `/families`
route to it). Spec: `docs/design/people-crm/engineering-spec.md` §1, §3.2,
§6 and §7 Phase 2.

| File | What it is |
|---|---|
| `domain/family_stage.py` | `roll_up_family_stage` and the precedence `pending_cancel > active > at_risk > on_hold > paused > trial > never_enrolled > left`; the Active / Leaving / Left scope tiles |
| `domain/family_index.py` | `FamilyRecord`, `FamilyChild`, `FamilyMoney`, `FamilyIndex`, and `search_family` (child and parent name word-prefix on `full_name_key`, email, legacy roster fields, phone by the last 7 to 10 digits) |
| `application/family_index.py` | `query_family_index` (scope, stage, class, card, overdue filters; sort before pagination) and `summarize_family_index` |
| `application/money_visibility.py` | `can_view_family_money(claims)`: the one money seam (#553); owner, admin and billing see amounts, front desk does not (`is_front_desk_only`), decided in `shared/auth/staff_tiers.py` |
| `application/ports.py` | `ParentAliasResolver`, `ChildLifecycleReader`, `FamilyMoneyReader` |
| `infrastructure/family_index_read_model.py` | `MongoFamilyIndexReadModel`: the whole academy's index in a fixed number of reads, cached 60 s per academy |

Wiring is `backend/v2/composition/families_crm.py`: identity's
`MongoUserRepository.resolve_parent_aliases`, enrollment's
`MongoStudentRepository.lifecycle_snapshots` and billing's
`MongoFamilyMoneyReadModel`. The CRM imports none of those contexts.

Rules the index keeps:

- **A family is keyed by the parent's canonical id** (`user_id`, else
  `auth_uid`, else the users `_id`). A student whose `parent_id` (or legacy
  `parent_user_id`) holds any alias (`user_id`, `firebase_uid`, `auth_uid`,
  users `_id`) lands in that family. Aliases are resolved with one `$in` per
  field, never an `$or` across fields (#878, #894). A parent reference no users
  document answers to is kept as its own family with `has_account = false`;
  the Billing tab 404s for those, as it always has.
- **Staff are excluded.** A user is in the index only when a student here
  references them or their membership here has the `parent` role (not
  `removed` or `suspended`). Children with no parent reference are not in the
  index (the Students page lists them).
- **The child state is the Students page's state.** `lifecycle_snapshots` is
  the same derivation `/admin/students` runs. The CRM only ranks it.
- **Money is the Billing tab's money.** `balance_cents` and
  `open_invoice_count` come from `billing/application/family_money.open_balance`,
  which `build_family_billing_view` also calls. Money is computed once and
  gated at serialization: when `can_view_family_money` is false every
  `money` block is `null`, `sort=balance` falls back to name and the Overdue
  filter matches nothing.
- **A failed secondary source is a warning, never a zero.** Money and class
  titles failing give `money_unavailable` / `classes_unavailable` in
  `warnings`; students, memberships, parents and lifecycles failing is a 503.

Not built yet (later phases): the R6 extension (application, waitlist and
trial states for children without enrollments), leads from `crm_contacts`
and applications in the index, `family_contacts` search keys, persisted
Groups (`family_groups`, Phase 4; today the summary returns static presets),
and the Not attending / Missing info / Needs attention chips.

## Family notes and follow-ups (People CRM Phase 4a, migration 0195)

Team notes and dated follow-ups on a family record. Spec:
`docs/design/people-crm/engineering-spec.md` §3.5 and §5. Coach notes are NOT
these records: they stay read-only (#665 data, child drawer) and the CRM
never writes them.

| File | What it is |
|---|---|
| `domain/family_notes.py` | `FamilyNote`, `FamilyFollowUp`, body/title normalisers and caps (4,000 / 200), `can_edit_note` (author or owner), `follow_up_bucket` |
| `application/family_directory.py` | `IndexFamilyDirectory`: "is this a family of this academy", over the family index (cached, re-checked once against a fresh build on a miss); resolves an alias to the canonical family id |
| `application/use_cases/family_notes.py` | `ListFamilyNotes`, `AddFamilyNote`, `EditFamilyNote`, `DeleteFamilyNote` |
| `application/use_cases/family_follow_ups.py` | `ListFamilyFollowUps`, `AddFamilyFollowUp`, `UpdateFamilyFollowUp`, `ListFollowUps` (the queue) |
| `infrastructure/mongo_family_notes_repo.py` | `MongoFamilyNoteRepository`, `MongoFamilyFollowUpRepository` (both `TenantScopedRepository`) |
| `backend/v2/migrations/0195_crm_family_notes_follow_ups.py` | the indexes |

Routes (`interfaces/admin/family_crm_routes.py`, all `require_persona("admin")`,
services on `app.state.admin_family_index` from `composition/families_crm.py`):

| Route | Notes |
|---|---|
| `GET/POST /admin/families/{parent_id}/notes` | newest first; live notes only |
| `PATCH/DELETE /admin/families/{parent_id}/notes/{note_id}` | author or owner (403 otherwise); DELETE is soft (`deleted_at`, `deleted_by`) |
| `GET/POST /admin/families/{parent_id}/follow-ups` | assignee must be an active admin or owner of this academy (422) |
| `PATCH /admin/families/{parent_id}/follow-ups/{follow_up_id}` | title, due date, assignee, `status` open/done (`done_at`, `done_by` stamped; reopening clears them) |
| `GET /admin/follow-ups?assignee=me\|all&bucket=overdue\|today\|upcoming\|done` | open rows by `due_on` against the academy's local today (no bucket = all open); done newest first |

### Records

`family_notes`: `{academy_id, parent_id, note_id, body, author_user_id,
created_at, updated_at, deleted_at?, deleted_by?}`. `body` is plain text,
line breaks kept, at most 4,000 characters, never rendered as HTML.

`family_follow_ups`: `{academy_id, parent_id, follow_up_id, title, due_on,
assignee_user_id, status (open|done), created_by, created_at, updated_at,
done_at?, done_by?}`. `due_on` is stored as an ISO `YYYY-MM-DD` string so it
sorts and range-compares as the date.

`parent_id` is always the **canonical** family id (the family index key), so
notes written from an alias URL land on the same family.

### Rules

- **The family check is the index, not tenant membership** (#664). Every use
  case first asks `FamilyDirectory` whether the id is a family of the caller's
  academy; another academy's family, or no family, is a 404.
- **Every repository read filters `academy_id` (tenant context) and
  `parent_id`**, so a note or follow-up id is only ever found on its own
  family. No body carries an academy.
- **Ids are unique per academy** through the unique indexes; a duplicate
  insert is `Crm.DuplicateRecordId` (409). The test fakes
  (`tests/fixtures/crm_family_fakes.py`) raise the same way.
- Coaches and parents get the wrong-persona 404 (`docs/security-matrix.md`).

### Indexes (migration 0195)

| Collection | Name | Keys | Options |
|---|---|---|---|
| `family_notes` | `family_notes_academy_note_unique` | `(academy_id, note_id)` | unique |
| `family_notes` | `family_notes_academy_parent_created` | `(academy_id, parent_id, created_at desc)` | |
| `family_follow_ups` | `family_follow_ups_academy_follow_up_unique` | `(academy_id, follow_up_id)` | unique |
| `family_follow_ups` | `family_follow_ups_academy_parent_created` | `(academy_id, parent_id, created_at desc)` | |
| `family_follow_ups` | `family_follow_ups_academy_assignee_status_due` | `(academy_id, assignee_user_id, status, due_on)` | |
| `family_follow_ups` | `family_follow_ups_academy_status_due` | `(academy_id, status, due_on)` | |

None is partial; no validator yet (same reasoning as 0192). Tests:
`tests/unit/test_crm_family_notes_domain.py`,
`tests/unit/test_crm_family_notes_use_cases.py`,
`tests/unit/test_0195_crm_family_notes_follow_ups.py`,
`tests/contract/test_crm_family_notes_real_mongo.py` (real `mongod`: tenant
isolation, duplicate ids, index use), and
`tests/interface/test_admin_family_crm_routes.py`.

Not built here: pinned notes, `student_id` tags, the `students.notes` copy,
`contact_id` (lead) notes, automatic follow-ups (`source`, `source_ref`), and
the timeline merge.

## Duplicate warning (People CRM Phase 4c, migration 0198)

"Possible match: <name> - open" on the forms that add a person: Add user /
Add parent (the Users directory dialog, which is how a family is added
today) and Add contact (the family record's Details tab). There is no staff
Add inquiry form yet (Pipeline quick add is a later phase); when it lands it
reuses `usePossibleDuplicateCheck` and `PossibleDuplicateNotice`
(`frontend/components/admin/possible-duplicate-notice.tsx`). A warning,
never a gate: nothing is merged and nothing is refused.

| File | What it is |
|---|---|
| `domain/duplicates.py` | normalisation (email lower-cased and trimmed, phone digits with both North American spellings, exact `full_name_key` name), the family-row matcher, masking |
| `application/use_cases/find_possible_duplicates.py` | `FindPossibleDuplicates`: family index, family contacts, members of this academy, inquiries; merged in code, at most 5 |
| `backend/v2/composition/people_duplicates.py` | wiring; identity's "user with this normalised email, only with an active membership HERE" adapter |
| `interfaces/admin/people_duplicate_routes.py` | `POST /admin/people/duplicate-check` |
| `backend/v2/migrations/0198_crm_duplicate_lookup_indexes.py` | the lookup indexes |

Rules:

- **Tenant-scoped.** The family index is built from the academy's own rows;
  `crm_contacts` and `family_contacts` lookups go through the
  `TenantScopedRepository`; a user is returned only with an active membership
  in the caller's academy. Nothing of another academy comes back
  (`tests/contract/test_crm_duplicate_check_real_mongo.py`,
  `tests/contract/test_two_tenant_isolation.py`).
- **Equality lookups on indexes, never `$or`.** One query per field and per
  phone spelling (`5550102030` and `15550102030`), merged in code. Users by
  `normalized_email` (`users_normalized_email_unique`), memberships by
  `(academy_id, user_id)`, contacts and inquiries by the 0198 indexes.
  Legacy users without a `normalized_email` are not looked up (parents among
  them are still matched through the family index).
- **Masked.** `jo***@example.test`, `•••-2030`. The link opens the record
  (`/admin/families/{id}` for a family, family contact or linked inquiry,
  `/admin/users/{id}` for a staff user; `null` for an unlinked inquiry).
- `require_persona("admin")`; rate-limited per client (60 a minute).

### Indexes (migration 0198)

| Collection | Name | Keys | Options |
|---|---|---|---|
| `crm_contacts` | `crm_contacts_academy_email_lookup` | `(academy_id, email)` | partial `{email: {$gt: ""}}` |
| `crm_contacts` | `crm_contacts_academy_phone_lookup` | `(academy_id, phone_digits)` | partial `{phone_digits: {$gt: ""}}` |
| `family_contacts` | `family_contacts_academy_email_lookup` | `(academy_id, email)` | partial `{email: {$gt: ""}}` |
| `family_contacts` | `family_contacts_academy_phone_lookup` | `(academy_id, phone_digits)` | partial `{phone_digits: {$gt: ""}}` |

Non-unique on purpose (a household shares an email or phone).

## CSV family and student import (roadmap L8a, migration 0199)

Backend only; the upload page is L8b. Replaces the live-academy import
scripts for new academies (`backend/scripts/import_blno.py` stays the
historical single-tenant script, still guarded).

| File | What it is |
|---|---|
| `domain/family_import.py` | the strict column schema, size caps, formula-injection sanitising, per-row validation, in-file family grouping |
| `domain/import_batches.py` | `ImportBatch`, `PlannedRow`, `ImportSummary`; the 24 h preview validity and the 5 min stale-claim window |
| `application/use_cases/family_import.py` | `PreviewFamilyImport`, `CommitFamilyImport`, `FamilyImportPlanner` |
| `infrastructure/mongo_import_batch_repo.py` | `MongoImportBatchRepository` (`import_batches`), `MongoImportAuditLog` (`audit_logs`) |
| `backend/v2/composition/family_import.py` | wiring (fresh family index, the duplicate finder's lookups, enrollment's `MongoStudentWriter.ensure_imported`) |
| `interfaces/admin/family_import_routes.py` | the two routes |
| `backend/v2/migrations/0199_import_batches.py` | the indexes |

Routes (`require_persona("admin")`, so owners and admins; coach, parent,
billing and front desk get the wrong-persona 404; rate-limited 10 a minute):

| Route | Body | Answer |
|---|---|---|
| `POST /admin/imports/families/preview` | `{filename?, csv}` (the file's text) | the stored batch: `import_batch_id`, `can_commit`, `summary`, one row result per data row |
| `POST /admin/imports/families/commit` | `{import_batch_id}` | the committed batch, `already_committed`, `students_inserted` |

### The file

UTF-8 CSV, at most 1 MB and 1,000 data rows, one row per child. Columns
(case-insensitive, each at most once; anything else refuses the file with
422 `Crm.InvalidImportFile`): `parent_name` and `student_name` (required),
`parent_email` and/or `parent_phone` (one of them per row), and
`student_date_of_birth` (`YYYY-MM-DD`, optional). Blank rows are skipped.
Row problems are per-row errors with the file's line number, not a refusal.

Formula injection: a name's leading `=`, `+`, `-`, `@` are removed (with a
warning); an email starting with one is an error; phones are stored as
digits only.

### What each row becomes

Rows are grouped into families by parent email, else by phone (a phone-only
row joins the emailed family with that phone). Each family is looked up with
`FindPossibleDuplicates` (the L1c finder) on a family index built fresh for
the call:

- email or phone matches exactly one existing family: the child joins it;
  a child that family already has (same `full_name_key`) is `skip`;
- matches two or more families, a family contact, or a staff account:
  an error (the import never guesses);
- no match: a **new roster family**. Its students carry `parent_id` (minted
  at preview, `parent_<ulid>`) and the `parent_name`, `parent_email` and
  `parent_phone` roster fields. No users document, no Firebase login, no
  email. Billing Setup's invite provisions the login later, as for any
  roster parent.

A matching inquiry, or a family with the same name only, is a warning.

The family index now reads the students' `parent_phone` too
(`FamilyRecord.legacy_phones`), and the duplicate matcher compares an email
against the students' `parent_email` (`legacy_contact_keys`), so roster
families (imported or legacy) are found by email and phone in the Add
family duplicate warning as well as here. That is what makes re-uploading
the same file a no-op: every row previews as `skip`.

### Idempotency

- Family and student ids are minted at preview and stored on the batch.
  Every student is written with `$setOnInsert` keyed by
  `(academy_id, student_id)`, and carries `import_batch_id` and
  `imported_by`.
- The commit claims the batch (`previewed` to `committing`, a conditional
  update), re-plans the stored rows against current data, refuses with
  409 `Crm.ImportNotCommittable` (`reason: has_errors`) when any row is an
  error (the batch goes back to `previewed` with the refreshed plan),
  writes, then marks it `committed`.
- A committed batch answers again with `already_committed: true` and
  writes nothing. A second concurrent commit gets 409 `in_progress`; a
  claim older than 5 minutes is a crashed commit and is resumed (the
  inserts are no-ops for rows already written). A preview older than 24 h
  is 409 `expired`.
- One `audit_logs` row per preview and per commit (`entity_type:
  "import_batch"`, counts only, no names or contacts).

### Record and indexes (migration 0199)

`import_batches`: `{academy_id, import_batch_id, kind: "families", status
(previewed|committing|committed), file_sha256, filename, created_by,
created_at, updated_at, rows[], summary{}, claimed_at?, committed_at?,
committed_by?, students_created?}`. Registered in `TENANT_OWNED_COLLECTIONS`.

| Name | Keys | Options |
|---|---|---|
| `import_batches_academy_batch_unique` | `(academy_id, import_batch_id)` | unique |
| `import_batches_academy_created` | `(academy_id, created_at desc)` | |

Tests: `tests/unit/test_crm_family_import_domain.py`,
`tests/unit/test_0199_import_batches.py`,
`tests/contract/test_crm_family_import_real_mongo.py` (real `mongod`:
re-upload no-op, repeated and concurrent commits, crash resume, re-plan,
errors blocking commit, cross-tenant), and
`tests/interface/test_admin_family_import_routes.py`.
