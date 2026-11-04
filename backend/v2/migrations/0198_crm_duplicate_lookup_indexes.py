"""Index the contact lookups behind the People CRM duplicate warning (Phase 4c).

``POST /admin/people/duplicate-check`` (``FindPossibleDuplicates``) asks, for
one academy, "is there already an inquiry or a family contact with this
email, or with this phone number?". Each question is an EQUALITY lookup on a
normalised field (email lower-cased and trimmed, phone as digits), asked once
per field and per phone spelling, never an ``$or`` across fields (#878/#894).

``explain()`` on a real ``mongod`` (7.0) with every earlier migration applied
showed each of those four lookups planned as ``IXSCAN`` on only the
``academy_id`` PREFIX of an unrelated index (``*_academy_contact_unique``)
plus a ``FETCH`` filter: it reads every inquiry or contact of the academy.
No existing index has ``email`` or ``phone_digits`` right after
``academy_id`` (``family_contacts``' email guard is ``(academy_id,
parent_id, email)``). So this adds four non-unique lookup indexes:

* every one leads with ``academy_id`` (#849), so a lookup never leaves the
  tenant;
* every one is PARTIAL on ``{field: {"$gt": ""}}``, the planner-usable shape
  (#878: never ``$type``). Rows without the field (an inquiry with no email,
  a family contact with no phone; ``crm_contacts`` stores a missing email as
  ``null``, which ``$gt: ""`` also leaves out) take no space, and an equality
  lookup on a non-empty string is served by the partial index;
* non-unique on purpose: two inquiries (or two families' contacts) may share
  a household email or phone. Duplicates are warned about, never refused.

New indexes on small collections (one row per inquiry or extra adult);
building them reads each collection once. Idempotent: ``create_index`` with
the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0198_crm_duplicate_lookup_indexes"

#: (collection, name, keys, options). Exposed so the unit test pins the shapes.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "crm_contacts",
        "crm_contacts_academy_email_lookup",
        [("academy_id", 1), ("email", 1)],
        {"partialFilterExpression": {"email": {"$gt": ""}}},
    ),
    (
        "crm_contacts",
        "crm_contacts_academy_phone_lookup",
        [("academy_id", 1), ("phone_digits", 1)],
        {"partialFilterExpression": {"phone_digits": {"$gt": ""}}},
    ),
    (
        "family_contacts",
        "family_contacts_academy_email_lookup",
        [("academy_id", 1), ("email", 1)],
        {"partialFilterExpression": {"email": {"$gt": ""}}},
    ),
    (
        "family_contacts",
        "family_contacts_academy_phone_lookup",
        [("academy_id", 1), ("phone_digits", 1)],
        {"partialFilterExpression": {"phone_digits": {"$gt": ""}}},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
