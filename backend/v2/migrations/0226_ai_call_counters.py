"""``ai_call_counters`` index (AI strategy Phase 3, slice D1, hard cap).

``(academy_id, key)`` unique: one counter per academy per UTC month
(``month:YYYY-MM``) and per academy, day and feature
(``day:YYYY-MM-DD:<feature>``). The unique index is what makes the
reservation's upsert safe: an upsert at the cap, or a second concurrent
first-of-the-period upsert, is refused instead of creating a duplicate
counter. New, empty collection. Idempotent (``create_index`` with the same
spec is a no-op).
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0226_ai_call_counters"

#: (collection, name, keys, options). Exposed so the unit test pins the shape.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "ai_call_counters",
        "ai_call_counters_academy_key_unique",
        [("academy_id", 1), ("key", 1)],
        {"unique": True},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
