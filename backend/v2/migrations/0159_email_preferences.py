"""Recipient email preference indexes (#555).

One row per recipient who has actually changed something — the absence of a
document means "opted in", so this collection stays small and never needs
back-filling.

The unique ``(academy_id, user_id)`` index is what makes the write an upsert
rather than a read-modify-write: two concurrent unsubscribe clicks converge on
one row instead of racing to create two. The ``(academy_id, email)`` index is
for audit lookups ("who unsubscribed with this address"), never for the send
gate — the gate keys off ``user_id``.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0159_email_preferences"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    preferences = db["email_preferences"]
    await preferences.create_index(
        [("academy_id", 1), ("user_id", 1)],
        unique=True,
        name="email_preferences_academy_user_unique",
    )
    await preferences.create_index(
        [("academy_id", 1), ("email", 1)],
        name="email_preferences_academy_email",
    )
