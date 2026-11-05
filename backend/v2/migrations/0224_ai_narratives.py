"""``ai_narratives`` indexes (AI strategy Phase 2, slice B4).

``(academy_id, student_id, for_date, kind)`` unique: one draft per child per
day per message kind, so a second "Draft tonight's note" replaces the first.
``(academy_id, status)`` serves the coach's pending list. New, empty
collection; idempotent (``create_index`` with the same spec is a no-op).
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0224_ai_narratives"

#: (collection, name, keys, options). Exposed so the unit test pins the shape.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "ai_narratives",
        "ai_narratives_academy_student_date_kind_unique",
        [("academy_id", 1), ("student_id", 1), ("for_date", 1), ("kind", 1)],
        {"unique": True},
    ),
    ("ai_narratives", "ai_narratives_academy_status", [("academy_id", 1), ("status", 1)], {}),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
