"""Make the per-academy id indexes serve lookups again (issue #849).

Migrations 0150, 0162 and 0186 built unique partial indexes on
``(academy_id, <id>)`` filtered on ``{"<id>": {"$type": "string"}}``. They
enforce uniqueness correctly, but MongoDB's planner cannot prove that an
equality lookup satisfies a ``$type`` filter, so it never uses them for
``{"academy_id": T, "<id>": X}``. 0162 and 0186 replaced ``sparse`` indexes
that DID serve those lookups, so every by-id read on ``students``,
``sessions``, ``enrollments``, ``session_occurrences`` and ``attendance``
fell back to scanning the academy's documents through some unrelated index.
Confirmed with ``explain()`` on production on 2026-09-21: 0 ms at under 100
documents per collection, but linear in the academy's data.

Each index is rebuilt with ``partialFilterExpression={"<id>": {"$gt": ""}}``,
which the planner uses for equality and ``$in``. By type bracketing it still
covers strings only, so absent and ``null`` ids stay out of the constraint as
before; ``""`` now stays out too.

Safety: ``$gt: ""`` selects a subset of what ``$type: "string"`` selects, and
the old index already guarantees that set is duplicate-free, so the create
cannot fail on existing data and no pre-flight is needed. Same key, so the
new index takes a new name and is created BEFORE the old one is dropped:
uniqueness is never absent. Re-running is a no-op.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0188_per_academy_id_indexes_planner_usable"

log = logging.getLogger(__name__)

#: (collection, id field, old ``$type`` index, new ``$gt`` index)
TARGETS: list[tuple[str, str, str, str]] = [
    ("students", "student_id", "student_id_unique_per_academy", "student_id_per_academy_uq"),
    (
        "students",
        "student_user_id",
        "student_user_id_unique_per_academy",
        "student_user_id_per_academy_uq",
    ),
    ("sessions", "session_id", "session_id_unique_per_academy", "session_id_per_academy_uq"),
    (
        "enrollments",
        "enrollment_id",
        "enrollment_id_unique_per_academy",
        "enrollment_id_per_academy_uq",
    ),
    (
        "session_occurrences",
        "occurrence_id",
        "session_occurrence_id_unique_per_academy",
        "session_occurrence_id_per_academy_uq",
    ),
    (
        "attendance",
        "attendance_id",
        "attendance_id_unique_per_academy",
        "attendance_id_per_academy_uq",
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, field, old_index, new_index in TARGETS:
        coll = db[collection]
        # Create first, drop second: uniqueness is never absent in between.
        await coll.create_index(
            [("academy_id", 1), (field, 1)],
            unique=True,
            partialFilterExpression={field: {"$gt": ""}},
            name=new_index,
        )
        existing = await coll.index_information()
        if old_index in existing:
            await coll.drop_index(old_index)
            log.info("0188: replaced $type-filtered %s with %s", old_index, new_index)
