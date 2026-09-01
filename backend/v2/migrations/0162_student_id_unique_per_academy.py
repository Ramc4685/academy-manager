"""Scope the students uniqueness constraint to the tenant (issue #610).

Migration 0010 built ``student_id_unique`` with ``_unique_v2_id``, i.e. a
single-field unique index on the BARE ``student_id``. That makes ``student_id``
globally unique across every academy, while every writer in the codebase
filters tenant-scoped (``{"student_id": X, "academy_id": T}``).

The two disagree, and the disagreement is the production 500 in #610:

* an admin adds a student whose ``student_id`` exists under a different
  ``academy_id`` (or on a legacy pre-tenancy doc with no ``academy_id`` at
  all);
* the tenant-scoped upsert filter misses, so the upsert degrades to an
  insert;
* the global index rejects the insert with ``E11000 duplicate key error
  collection: students index: student_id_unique``;
* the route 500s — deterministically, for that student, forever — after the
  seat has already been reserved.

Replaced with a unique partial index on ``(academy_id, student_id)``, matching
how the data is actually read and written. ``partialFilterExpression`` on
``$type: "string"`` (rather than ``sparse``) keeps docs that predate the field
out of the constraint instead of colliding them all on ``null``.

Safety: the new index is created BEFORE the old one is dropped, so the
collection is never left unprotected, and a genuine ``(academy_id,
student_id)`` duplicate makes the create fail loudly with the offending pairs
named rather than silently removing uniqueness. Cross-*academy* reuse of a
``student_id`` is exactly what this migration legalises, so it is reported as
information, not an abort.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0162_student_id_unique_per_academy"

log = logging.getLogger(__name__)

_OLD_INDEX = "student_id_unique"
_NEW_INDEX = "student_id_unique_per_academy"


async def _duplicate_pairs(students) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """(academy_id, student_id) pairs that would break the new index."""
    cursor = students.aggregate(
        [
            {"$match": {"student_id": {"$type": "string"}}},
            {
                "$group": {
                    "_id": {"academy_id": "$academy_id", "student_id": "$student_id"},
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 20},
        ]
    )
    return [doc async for doc in cursor]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    students = db["students"]

    # Pre-flight: name the collisions before touching a live constraint, so a
    # failure here is a readable message and not an opaque E11000 mid-drop.
    duplicates = await _duplicate_pairs(students)
    if duplicates:
        offenders = ", ".join(
            f"{row['_id'].get('academy_id')!r}/{row['_id'].get('student_id')!r} x{row['count']}"
            for row in duplicates
        )
        raise RuntimeError(
            "0162 aborted: students already contains duplicate "
            f"(academy_id, student_id) pairs, so {_NEW_INDEX} cannot be "
            f"created. Deduplicate these first (up to 20 shown): {offenders}. "
            f"The old global {_OLD_INDEX} index has been left in place."
        )

    # Create first, drop second: uniqueness is never absent in between.
    await students.create_index(
        [("academy_id", 1), ("student_id", 1)],
        unique=True,
        partialFilterExpression={"student_id": {"$type": "string"}},
        name=_NEW_INDEX,
    )

    existing = await students.index_information()
    if _OLD_INDEX in existing:
        await students.drop_index(_OLD_INDEX)
        log.info("0162: dropped globally-unique %s in favour of %s", _OLD_INDEX, _NEW_INDEX)
