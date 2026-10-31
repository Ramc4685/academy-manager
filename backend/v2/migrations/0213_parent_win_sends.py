"""Parent evening win e-mail claims.

Unique ``(academy_id, parent_id, digest_date)`` on ``parent_win_sends``, the
same idempotency index the parent digest has (migration 0148): a family gets
at most one evening win e-mail per academy-local day.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0213_parent_win_sends"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    sends = db["parent_win_sends"]
    await sends.create_index("digest_id", unique=True, name="parent_win_send_id_unique")
    await sends.create_index(
        [("academy_id", 1), ("parent_id", 1), ("digest_date", 1)],
        unique=True,
        name="parent_win_sends_academy_parent_date_unique",
    )
