"""Push-notification device tokens (mobile M2).

Unique ``token`` across academies: one FCM token is one app install, held by
one user at a time (registering it again moves the row). ``(academy_id,
user_id)`` serves the per-recipient lookup the push channel (M3) will make.
New empty collection, so both builds are instant.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0215_push_devices"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    devices = db["push_devices"]
    await devices.create_index("token", unique=True, name="push_devices_token_unique")
    await devices.create_index(
        [("academy_id", 1), ("user_id", 1)], name="push_devices_academy_user"
    )
