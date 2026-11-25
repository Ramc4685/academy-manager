"""Parent drop-off check-ins (new, empty collection: no backfill).

``dropoff_checkins_occurrence_student_uq``: unique
``(academy_id, occurrence_id, student_id)``. One arrival report per child per
dated class: a repeat tap or two racing reports store one row, and every
status transition and the per-class roster read are served by it. All three
fields are always set, so no partial filter is needed.

Re-running is a no-op.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0246_dropoff_checkins"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["dropoff_checkins"].create_index(
        [("academy_id", 1), ("occurrence_id", 1), ("student_id", 1)],
        unique=True,
        name="dropoff_checkins_occurrence_student_uq",
    )
