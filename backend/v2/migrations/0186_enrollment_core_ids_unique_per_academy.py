"""Scope enrollment-core id uniqueness to the tenant (issue #849, batch 1).

Migrations 0010, 0020 and 0081 built single-field unique indexes on the BARE
id of ``sessions``, ``enrollments``, ``attendance`` and
``session_occurrences``. That makes each id globally unique across every
academy, while every reader and writer filters tenant-scoped
(``{"<id>": X, "academy_id": T}``). It is the #610 trap that migration 0162
fixed for ``students`` only: a second academy carrying the same id (imported,
copied or restored data) misses the scoped upsert filter, degrades to an
insert, and the global index rejects it with E11000 — a deterministic 500.

Each is replaced with a unique partial index on ``(academy_id, <id>)``.
``partialFilterExpression`` on ``$type: "string"`` (rather than ``sparse``)
keeps docs that predate the field out of the constraint instead of colliding
them all on ``null``.

Safety: every collection is pre-flighted BEFORE any index is touched, so one
dirty collection aborts the whole batch with the offenders named rather than
leaving it half-swapped. Per collection the new index is created before the
old one is dropped, so uniqueness is never absent. Re-running is a no-op.

Verified against production on 2026-09-21: all four global indexes present,
no ``(academy_id, <id>)`` twin, zero duplicate pairs, zero docs without a
string ``academy_id``.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0186_enrollment_core_ids_unique_per_academy"

log = logging.getLogger(__name__)

#: (collection, id field, old global index, new per-academy index)
TARGETS: list[tuple[str, str, str, str]] = [
    ("sessions", "session_id", "session_id_unique", "session_id_unique_per_academy"),
    ("enrollments", "enrollment_id", "enrollment_id_unique", "enrollment_id_unique_per_academy"),
    (
        "session_occurrences",
        "occurrence_id",
        "session_occurrence_id_unique",
        "session_occurrence_id_unique_per_academy",
    ),
    ("attendance", "attendance_id", "attendance_id_unique", "attendance_id_unique_per_academy"),
]


async def _duplicate_pairs(collection, field: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """(academy_id, <id>) pairs that would break the new index."""
    cursor = collection.aggregate(
        [
            {"$match": {field: {"$type": "string"}}},
            {
                "$group": {
                    "_id": {"academy_id": "$academy_id", "id": f"${field}"},
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 20},
        ]
    )
    return [doc async for doc in cursor]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    # Pre-flight every collection before touching a live constraint, so a
    # failure is a readable message and the batch is all-or-nothing.
    problems: list[str] = []
    for collection, field, _old_index, new_index in TARGETS:
        duplicates = await _duplicate_pairs(db[collection], field)
        if duplicates:
            offenders = ", ".join(
                f"{row['_id'].get('academy_id')!r}/{row['_id'].get('id')!r} x{row['count']}"
                for row in duplicates
            )
            problems.append(
                f"{collection} has duplicate (academy_id, {field}) pairs, so "
                f"{new_index} cannot be created (up to 20 shown): {offenders}"
            )
    if problems:
        raise RuntimeError(
            "0186 aborted before changing any index. Deduplicate these first: "
            + "; ".join(problems)
            + ". The old global indexes have been left in place."
        )

    for collection, field, old_index, new_index in TARGETS:
        coll = db[collection]
        # Create first, drop second: uniqueness is never absent in between.
        await coll.create_index(
            [("academy_id", 1), (field, 1)],
            unique=True,
            partialFilterExpression={field: {"$type": "string"}},
            name=new_index,
        )
        existing = await coll.index_information()
        if old_index in existing:
            await coll.drop_index(old_index)
            log.info("0186: dropped globally-unique %s in favour of %s", old_index, new_index)
