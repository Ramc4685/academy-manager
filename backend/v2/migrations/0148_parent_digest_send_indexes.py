"""Parent daily digest-send indexes.

Mirrors the coach digest (migration 0125). The unique
``(academy_id, parent_id, digest_date)`` index is the idempotency guard: the
send use case inserts against it, so a family is e-mailed at most once per day
even if the hourly scheduler fires more than once. Kept in its own
``parent_digest_sends`` collection so the admin coach-digest log stays coach-only
and a person who is both coach and parent cannot collide on one shared index.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0148"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    sends = db["parent_digest_sends"]
    await sends.create_index(
        "digest_id",
        unique=True,
        name="parent_digest_send_id_unique",
    )
    await sends.create_index(
        [("academy_id", 1), ("parent_id", 1), ("digest_date", 1)],
        unique=True,
        name="parent_digest_sends_academy_parent_date_unique",
    )
