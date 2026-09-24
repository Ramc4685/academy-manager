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
`linked_user_id`) exist in the model and are read back by the repository, but
no use case writes them yet. `pipeline_override` is written only by
`MoveCardOnPipeline` (see "Pipeline moves" below).

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
`contact_id` (lead) notes. Automatic follow-ups landed in L3c (`source_key`,
below); the timeline merge is Phase 5 (below).

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

## Pipeline moves and trial outcomes (People CRM L3a)

Spec §3.4: "Moves that correspond to a real write (approve trial, Came /
Didn't come) call the existing use cases; moves without one write
`crm_contacts.pipeline_override` with author and time so the board never lies
about the system state." L3a ships both halves as backend plus minimal
buttons; the board view itself is L3b (next section).

| File | What it is |
|---|---|
| `domain/pipeline.py` | the five board columns `inquiry, trial_booked, trial_done, registered, enrolled`, `current_column` (system `enrolled` > override > column implied by `pipeline_status`) and the stage-skip guard `refuse_move` |
| `application/use_cases/pipeline_moves.py` | `MoveCardOnPipeline`: tenant-scoped read, guard, compare-and-swap write of `{column, set_by, set_at}` plus `updated_at` |
| `infrastructure/mongo_crm_contact_repo.py` | `set_pipeline_override(contact_id, override, expected_column=, updated_at=)` |
| `backend/v2/composition/crm_pipeline.py` | wiring (lazy, `app.state.crm_pipeline_moves`) |
| `interfaces/admin/pipeline_routes.py` | `POST /admin/crm/contacts/{contact_id}/pipeline-move` `{to_column}` |

Guard rules: forward one column at a time (`stage_skip`), backward any number
(a correction), never to `enrolled` (only the conversion flow enrolls; the
route refuses it as a 422, the use case as `needs_system_write`), and an
enrolled contact never moves (`contact_enrolled`). A move to the column the
card already shows is a no-op that keeps the first author. The write matches
only while the stored override is the one read and the row is not
`enrolled`, so of two concurrent moves one lands and the other gets
`Crm.PipelineMoveNotAllowed` (409) with `reason = "changed"`. Another
academy's id is `Crm.ContactNotFound` (404). No new index: the write is an
equality on `(academy_id, contact_id)` (`crm_contacts_academy_contact_unique`).

**Came / Didn't come** is the enrollment context's `MarkTrialOutcome`
(`contexts/enrollment/application/use_cases/trial_outcomes.py`, wired by
`composition/trial_outcomes.py`): an `approved` trial with an assigned, not
cancelled date, from one hour before it starts, becomes `completed` with
`outcome` (`came` | `no_show`), `outcome_by` and `outcome_at` on the
`trial_requests` row; a completed trial may be corrected; `converted`,
`pending` and `denied` refuse (409 `Enrollment.TrialOutcomeNotAllowed`,
`details.reason`). Routes: `POST /admin/self-service/trials/{request_id}/outcome`
(admin Inbox trial rows, `require_persona("admin")` like approve/deny) and
`POST /coach/trials/{request_id}/outcome` (coach Today trial rows; a coach only
for sessions they coach or assist, anything else is the unknown-id 404; a coach
supervisor for any trial of the academy). `GET /coach/today` trial rows carry
`trial_request_id` and `trial_outcome`. Prospective-child trials are not on the
coach roster (no student to roster, a v1 limitation), so they are marked from
the admin Inbox.

Tests: `tests/unit/test_mark_trial_outcome.py`, `tests/unit/test_crm_pipeline_moves.py`,
`tests/interface/test_trial_outcome_and_pipeline_routes.py`,
`tests/contract/test_trial_outcome_pipeline_real_mongo.py` (real `mongod`: the
status and override compare-and-swaps, tenant isolation, concurrent moves),
`frontend/e2e/specs/trial-outcome.spec.ts`.

## The Pipeline board (People CRM L3b)

`/admin/families?view=pipeline` (a view on the existing Families route, no new
page; deep link `?view=pipeline&stage=trial_booked` picks the phone stage).
Spec §3.4.

| File | What it is |
|---|---|
| `application/pipeline_board.py` | `build_pipeline_board` (pure merge), `GetPipelineBoard`, `move_targets`, `quick_add_command` |
| `backend/v2/composition/crm_pipeline.py` | lazy wiring: `app.state.crm_pipeline_board` (reuses `app.state.admin_family_index.index`, so the board shares the index cache) and `app.state.crm_quick_add` (the existing `CreateContact`) |
| `interfaces/admin/pipeline_routes.py` | `GET /admin/crm/pipeline`, `POST /admin/crm/contacts` (quick add) |
| `frontend/components/admin/people/pipeline-board.tsx` | the board, the phone stage switcher, Move to... and quick add |

Where a card sits:

- **`crm_contacts`** (newest first, at most 500): `current_column` (system
  `enrolled` > staff override > the stage's column). `move_targets` lists the
  columns `refuse_move` allows now; an enrolled contact has none. An enrolled
  card leaves the board 7 days after its last change.
- **The family index roll-up**: stage `trial` is a Trial booked card, a family
  with an account and no enrolled child (`never_enrolled`) is an Inquiry card.
  Family cards are read-only (their stage is a system write made on the family
  record or the Inbox) and open `/admin/families/{id}`. A family a contact
  links to (`linked_family_id` / `converted_parent_id`, any alias) is not shown
  twice. Active, leaving and left families are not on the board.
- A failed family index read is the `families_unavailable` warning; the
  contact cards still show.

No card carries money, so every admin-persona tier sees the same board. Quick
add takes a staff source only (`whatsapp_or_phone`, `referral`, `other`; the
route refuses `website` and extra fields), stamps `created_by`, stage `lead`,
`consent.contact_about_request = true`, never marketing. Staff rows are not
deduped (see "Idempotency"): the form disables its button while saving and
shows the Phase 4c duplicate warning.

UI rules: moves are a "Move to..." button opening radio options with an
explicit Move button (nothing commits on change, WCAG 3.2.2); Escape closes
it and returns focus to the button; after a card leaves its column focus
goes to the card that took its place, else the column heading (WCAG 2.4.3).

Tests: `tests/unit/test_crm_pipeline_board.py`,
`tests/interface/test_crm_pipeline_board_routes.py`,
`tests/contract/test_crm_pipeline_board_real_mongo.py` (real `mongod`: tenant
scope, newest first, a move shows on the next read, staff rows never deduped),
`frontend/e2e/specs/admin-pipeline-board.spec.ts`.

Not built here: the Registered and Trial done columns for families (they
need the application and trial joins of the R6 extension), card assignee,
last contact and Cold chip. The auto follow-up is L3c, below.

## Trial passed, no registration (People CRM L3c, migration 0201)

A daily scheduled job, `create_trial_follow_ups` (04:50 scheduler time,
leased, heartbeat in `ops_job_runs`, stale after 26h), runs
`CreateTrialPassedFollowUps` once per academy inside its `tenant_scope`.
For every trial marked **Came** (`status: completed`, `outcome: came`, no
`linked_application_id`) whose assigned, not-cancelled class started between
60 and 7 days ago, it adds one family follow-up:

| Field | Value |
| --- | --- |
| `title` | `Trial passed, no registration` (`: <child>` for a prospective child) |
| `parent_id` | the canonical family (family index); an unknown parent is skipped |
| `assignee_user_id` | the academy's earliest active owner, else `""` (shown as "Unassigned") |
| `due_on` | the academy's local today |
| `created_by` | `system:trial_follow_up` |
| `source_key` | `trial_passed:<trial request id>` |

Rules:

- **Idempotent per trial.** The write is `add_once`: one upsert on
  `(academy_id, source_key)` with `$setOnInsert`, backed by a unique index.
  A rerun, a second machine, or a follow-up staff already marked done never
  produces a second row; a racing duplicate-key error reads as "already
  there".
- **No-op when registered.** The family registered after requesting the
  trial when an `onboarding_applications` row of the parent, past `DRAFT` /
  `CHECKOUT_EXPIRED` / `ABANDONED`, was created or updated since; or, for an
  existing child, a non-terminal enrollment on the trial's class exists.
- **Per academy.** Every read is tenant-scoped (repositories) or filters
  `academy_id` explicitly (the composition's direct reads).
- A follow-up a person adds stores `source_key: null` and is outside the
  index. No email, no money.

The CRM does not import enrollment, onboarding or identity: the reads are
ports (`PassedTrialSource`, `RegistrationCheck`, `AcademyOwnerLookup`,
`SourcedFollowUpWriter`) implemented in `composition/trial_follow_ups.py`.

### Index (migration 0201)

| Collection | Name | Keys | Options |
| --- | --- | --- | --- |
| `family_follow_ups` | `family_follow_ups_academy_source_key_unique` | `academy_id, source_key` | unique, partial `{source_key: {$gt: ""}}` |

Tests: `tests/unit/test_crm_trial_follow_ups.py`,
`tests/unit/test_0201_crm_follow_up_source_key.py`,
`tests/contract/test_crm_trial_follow_ups_real_mongo.py` (real `mongod`:
one row per trial, rerun and 5 concurrent runs, done not recreated,
cross-tenant, registered no-op, draft and other-academy applications
ignored, window and outcome filters, manual follow-ups coexist).

## Unified family timeline (People CRM Phase 5, migration 0202)

`GET /admin/families/{parent_id}/timeline?before=<cursor>&limit=<1..200>`
(`interfaces/admin/family_timeline_routes.py`, `require_persona("admin")`,
use case on `app.state.admin_family_index.timeline`, wired by
`composition/family_timeline.py`). Spec: engineering spec §5 "Timeline".
The family record's Timeline tab reads it; the Billing tab keeps billing's
own timeline.

| File | What it is |
|---|---|
| `domain/timeline.py` | `TimelineEntry`, merge (newest first, `entry_id` tiebreak), dedupe, cap, cursor paging, `redact_money`, `AUDIT_ACTION_ALLOWLIST` |
| `application/timeline.py` | `GetFamilyTimeline`; the billing and coach-note source adapters |
| `infrastructure/family_timeline_sources.py` | attendance, requests, admin audit (allowlist + moved family), CRM records |
| `backend/v2/migrations/0202_family_timeline_indexes.py` | the lookup indexes |

Sources (each read newest first, at most 200 rows per query, all under
`gather`; a failing source adds `"<name>_unavailable"` to `warnings`):

| Kind | Source |
|---|---|
| money, lifecycle, comms, billing admin actions | billing's `build_timeline` through the family billing read model (called as one source, not extended). Its lifecycle events cover every enrollment of the family's children. |
| attendance | `attendance` absent marks and corrections of the children, dated by the occurrence `start_at` |
| requests | `absence_notices`, `pause_requests`, `makeup_requests` by child; `trial_requests` by parent alias (one equality per alias) |
| coach | shared coach notes (#665), read-only, with the coach's name |
| admin | `audit_logs` on the parent aliases, children and their enrollments, action in `AUDIT_ACTION_ALLOWLIST` only (never `user_logged_in`); `student.parent_changed` rows become "Moved from family X" on the new family and "Moved to family Y" on the old one, found by `old_parent_id` / `new_parent_id` one alias at a time |
| crm | family notes (body as `detail`), follow-ups (added, done), family contacts |

Rules:

- **The family check is the index** (#664): another academy's family, or no
  family, is `Crm.FamilyNotFound` (404). The children and the canonical id
  come from the index row; the parent's aliases from identity.
- **Dedupe**: non-money entries with the same `enrollment_id` within 10
  minutes of the cluster's first entry collapse into one (lifecycle kept
  first); the others' codes are in `collapsed_codes`. Money never collapses.
- **Times** go through `as_utc` (#706). The merged feed is cut to 200.
- **Paging**: `next_cursor` is an opaque token of the last entry's time and
  id; sources are asked only for rows at or before it.
- **Money** is gated at serialization by `can_view_family_money` (#553): a
  caller who may not see amounts gets money rows without `amount_cents` /
  `refunded_cents` and without dollar figures in the summary, and
  `money_visible: false`.

### Indexes (migration 0202)

| Collection | Name | Keys | Options |
|---|---|---|---|
| `audit_logs` | `audit_logs_academy_entity_created` | `(academy_id, entity_id, created_at desc)` | |
| `audit_logs` | `audit_logs_academy_old_parent_created` | `(academy_id, old_parent_id, created_at desc)` | partial `{old_parent_id: {$gt: ""}}` |
| `audit_logs` | `audit_logs_academy_new_parent_created` | `(academy_id, new_parent_id, created_at desc)` | partial `{new_parent_id: {$gt: ""}}` |
| `absence_notices` | `absence_notices_academy_student_submitted` | `(academy_id, student_id, submitted_at desc)` | |
| `pause_requests` | `pause_requests_academy_student_created` | `(academy_id, student_id, created_at desc)` | |
| `makeup_requests` | `makeup_requests_academy_student_created` | `(academy_id, student_id, created_at desc)` | |

Tests: `tests/unit/test_crm_timeline_domain.py`,
`tests/unit/test_crm_family_timeline_use_case.py`,
`tests/unit/test_0202_family_timeline_indexes.py`,
`tests/interface/test_admin_family_timeline_routes.py`,
`tests/contract/test_crm_family_timeline_real_mongo.py` (real `mongod`:
allowlist, moved entries on both families, tenant isolation, index use).

Not built here (see the Messages tab below for sends and logged contacts):
registration (applications, waivers) and inquiry (`crm_contacts`) entries,
and staff display names for `actor_id`.

## Family Messages tab (People CRM Phase 6, roadmap L4c, migration 0203)

`GET /admin/families/{parent_id}/messages`,
`POST /admin/families/{parent_id}/messages/log`,
`PATCH /admin/families/{parent_id}/messages/log/{log_id}`
(`interfaces/admin/family_messages_routes.py`, `require_persona("admin")`,
use cases on `app.state.admin_family_index.messages`, wired by
`composition/family_messages.py`). The family record's Messages tab reads it.

| File | What it is |
|---|---|
| `domain/family_messages.py` | `FamilyContactLog`, `MessageEntry`, merge (newest first, `entry_id` tiebreak, cap 200), note normalisation, who may complete a log |
| `application/family_messages.py` | `GetFamilyMessages`, `LogFamilyContact`, `CompleteFamilyContactLog` |
| `infrastructure/family_message_sources.py` | campaign deliveries, parent digest, absence-notice confirmations, invoice copies, the staff log |
| `infrastructure/mongo_family_contact_log_repo.py` | `family_contact_log` (tenant-scoped) |
| `backend/v2/migrations/0203_family_contact_log.py` | its indexes |

Thread sources (all under `gather`; a failing source adds
`"<name>_unavailable"` to `warnings`, never a 500):

| Source | Rows |
|---|---|
| `campaigns` | `message_deliveries` to any parent alias, subject from `message_campaigns` |
| `digest` | `parent_digest_sends` of any parent alias; `skipped_empty` left out |
| `absence_notices` | `absence_notice_sends` with audience `parent` for the children's notices (the staff alert is not a message to the family) |
| `invoice_copies` | `invoice_contact_email_sends` (0197) matched on the family contact's email AND `contact_id` |
| `contact_log` | `family_contact_log`: WhatsApp / SMS / email sent from the staff member's own app, a call, a talk in person |

Rules:

- **No app-sent SMS or WhatsApp.** The tab opens `wa.me` / `sms:` / `mailto:`
  and asks "Did you send it?": yes stores `status: logged`, "Not yet" stores
  `not_logged` so the handoff can be confirmed later (by its author or an
  owner, `Crm.ContactLogEditForbidden` otherwise). "Send from the app
  (coming)" is shown disabled. A call or in-person talk is always `logged`.
- **The family check is the index** (#664): another academy's family, or no
  family, is `Crm.FamilyNotFound` (404); a log id of another family is
  `Crm.ContactLogNotFound` (404).
- **No money** is read or returned, so every staff tier sees the same thread.

### Indexes (migration 0203)

| Collection | Name | Keys | Options |
|---|---|---|---|
| `family_contact_log` | `family_contact_log_academy_log_id_unique` | `(academy_id, log_id)` | unique |
| `family_contact_log` | `family_contact_log_academy_parent_created` | `(academy_id, parent_id, created_at desc)` | |

Tests: `tests/unit/test_crm_family_messages.py`,
`tests/unit/test_0203_family_contact_log.py`,
`tests/interface/test_admin_family_messages_routes.py`,
`tests/contract/test_crm_family_messages_real_mongo.py` (real `mongod`).
