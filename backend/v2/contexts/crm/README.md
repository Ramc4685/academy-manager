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
`0192_crm_contacts`. **It ships no route and no composition wiring.** Each
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

## Tests

- `backend/v2/tests/unit/test_crm_create_contact.py`: behaviour, validation,
  dedupe, against the real repository and the 0192 indexes (mongomock).
- `backend/v2/tests/unit/test_0192_crm_contacts.py`: index shapes.
- `backend/v2/tests/contract/test_crm_contacts_are_academy_scoped.py`:
  cross-academy reads see nothing; writes stamp the tenant.
- `backend/v2/tests/contract/test_partial_index_planner_usability.py`: the
  dedupe lookup is served by its index on a real `mongod`.
