"""Coach daily digest-send indexes.

The unique ``(academy_id, coach_id, digest_date)`` index is the idempotency
guard for the daily digest: ``try_claim`` inserts against it, so a coach is
e-mailed at most once per day even if the scheduler fires more than once.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0125"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    sends = db["coach_digest_sends"]
    await sends.create_index(
        "digest_id",
        unique=True,
        name="coach_digest_send_id_unique",
    )
    await sends.create_index(
        [("academy_id", 1), ("coach_id", 1), ("digest_date", 1)],
        unique=True,
        name="coach_digest_sends_academy_coach_date_unique",
    )
