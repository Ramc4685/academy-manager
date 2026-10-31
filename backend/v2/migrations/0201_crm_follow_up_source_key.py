"""Unique ``(academy_id, source_key)`` on ``family_follow_ups`` (roadmap L3c).

The "Trial passed, no registration" job writes one follow-up per trial,
keyed ``source_key = "trial_passed:<trial id>"``. This index is what makes
that "one": the job's upsert on the key cannot insert twice, even when two
machines run the same tick.

Partial on ``{"source_key": {"$gt": ""}}``, never ``$type`` / ``$exists``
(#878): a follow-up a person adds stores ``source_key: null`` (or has no
field on rows written before this change) and stays outside the index, so
any number of those coexist. The job's lookup is an equality on a non-empty
string, which the planner serves from this partial index. Leads with
``academy_id`` (#849). No data to move.

Idempotent: ``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0201_crm_follow_up_source_key"

#: (collection, name, keys, options). Exposed so the unit test pins the shape.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "family_follow_ups",
        "family_follow_ups_academy_source_key_unique",
        [("academy_id", 1), ("source_key", 1)],
        {"unique": True, "partialFilterExpression": {"source_key": {"$gt": ""}}},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
