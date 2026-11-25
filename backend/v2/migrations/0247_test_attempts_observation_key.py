"""One class observation per class, child and skill on ``test_attempts``.

``test_attempts_observation_uq``: unique ``(academy_id, observation_key)``,
partial on ``observation_key > ""``. A quick pass recorded in a dated class
carries ``occurrence:student:skill`` as its key, so a retry, a second writer or
a resumed recap save stores one attempt and every later effect replays from
it. Formal tests have no key (the field is absent) and may repeat freely.
Existing rows have no key: nothing to backfill.

Re-running is a no-op.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0247_test_attempts_observation_key"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["test_attempts"].create_index(
        [("academy_id", 1), ("observation_key", 1)],
        unique=True,
        partialFilterExpression={"observation_key": {"$gt": ""}},
        name="test_attempts_observation_uq",
    )
