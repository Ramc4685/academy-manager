"""Create the idempotency_keys collection index + TTL.

See shared/idempotency/.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0001"


async def up(db: AsyncIOMotorDatabase) -> None:
    coll = db["idempotency_keys"]
    await coll.create_index("key", unique=True, name="key_unique")
    # 7-day TTL.
    await coll.create_index(
        "created_at", expireAfterSeconds=7 * 24 * 60 * 60, name="created_at_ttl"
    )
