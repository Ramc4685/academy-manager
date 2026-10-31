"""Create the indexes for ``crm_contacts``, the shared lead store.

One store for the People CRM (docs/design/people-crm/engineering-spec.md §5)
and the public tenant page's anonymous trial-request form (source
``website``). The record, repository and ``CreateContact`` use case live in
``backend/v2/contexts/crm``; its README is the consumer contract.

New collection, no data to move: Mongo creates it on the first
``create_index``. Every index leads with ``academy_id`` (#849). The dedupe
index is partial on ``{"dedupe_key": {"$gt": ""}}``, the planner-usable shape
(#878 / 0188), never ``$type`` or ``$exists``; ``CreateContact`` writes a key
only for ``website`` rows and omits the field for staff sources, so the
filter leaves staff quick-add rows out of the unique index.

No ``$jsonSchema`` validator yet: two consumers are still settling the shape
and a dormant validator rejects writes anywhere (#657). Add one in a later
migration once both have shipped.

Idempotent: ``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0192_crm_contacts"

COLLECTION = "crm_contacts"

#: (name, keys, options). Exposed so the unit test pins the exact shapes.
INDEXES: list[tuple[str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "crm_contacts_academy_contact_unique",
        [("academy_id", 1), ("contact_id", 1)],
        {"unique": True},
    ),
    (
        "crm_contacts_academy_dedupe_unique",
        [("academy_id", 1), ("dedupe_key", 1)],
        {"unique": True, "partialFilterExpression": {"dedupe_key": {"$gt": ""}}},
    ),
    (
        "crm_contacts_academy_pipeline_created",
        [("academy_id", 1), ("pipeline_status", 1), ("created_at", -1)],
        {},
    ),
    (
        "crm_contacts_academy_created",
        [("academy_id", 1), ("created_at", -1)],
        {},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    coll = db[COLLECTION]
    for name, keys, options in INDEXES:
        await coll.create_index(keys, name=name, **options)
