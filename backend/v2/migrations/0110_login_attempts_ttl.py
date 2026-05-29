"""Login attempt retention indexes."""

from __future__ import annotations

from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0110_login_attempts_ttl"


async def up(db: AsyncIOMotorDatabase) -> None:
    cursor = db["login_attempts"].find({"updated_at": {"$type": "string"}})
    async for doc in cursor:
        parsed = _parse_datetime(str(doc.get("updated_at") or ""))
        if parsed is not None:
            await db["login_attempts"].update_one(
                {"_id": doc["_id"]},
                {"$set": {"updated_at": parsed}},
            )
    await db["login_attempts"].create_index(
        [("updated_at", 1)],
        expireAfterSeconds=86400,
        name="login_attempts_updated_at_ttl",
    )


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
