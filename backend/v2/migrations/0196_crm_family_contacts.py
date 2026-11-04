"""Create the indexes for ``family_contacts`` and ``family_details`` (People CRM Phase 4b).

Second parents, guardians and other adults on a family, with the opt-in
"Gets notices" / "Gets invoices" switches, plus the family's editable
details (docs/design/people-crm/engineering-spec.md §4-§5). New collections,
no data to move: Mongo creates each on the first ``create_index``.

Every index leads with ``academy_id`` (#849):

* ``(academy_id, contact_id)`` unique: a contact id is unique per academy.
* ``(academy_id, parent_id, created_at)``: the family's contact list, and the
  audience resolver's per-parent expansion (``parent_id`` equality or ``$in``).
* ``(academy_id, parent_id, email)`` unique and PARTIAL on
  ``{email: {$gt: ""}}``: one contact per email within a family. A contact
  without an email stores no ``email`` field and takes no slot. The filter is
  ``$gt: ""``, never ``$type`` (#878: the planner ignores ``$type`` partial
  indexes for equality lookups); nothing queries this index with ``$or``.
* ``family_details (academy_id, parent_id)`` unique: one details document per
  family, so two racing first saves converge on one row.

No ``$jsonSchema`` validator (#657): the shape is new; add one once it has
settled.

Idempotent: ``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0196_crm_family_contacts"

#: (collection, name, keys, options). Exposed so the unit test pins the shapes.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "family_contacts",
        "family_contacts_academy_contact_unique",
        [("academy_id", 1), ("contact_id", 1)],
        {"unique": True},
    ),
    (
        "family_contacts",
        "family_contacts_academy_parent_created",
        [("academy_id", 1), ("parent_id", 1), ("created_at", 1)],
        {},
    ),
    (
        "family_contacts",
        "family_contacts_academy_parent_email_unique",
        [("academy_id", 1), ("parent_id", 1), ("email", 1)],
        {"unique": True, "partialFilterExpression": {"email": {"$gt": ""}}},
    ),
    (
        "family_details",
        "family_details_academy_parent_unique",
        [("academy_id", 1), ("parent_id", 1)],
        {"unique": True},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
