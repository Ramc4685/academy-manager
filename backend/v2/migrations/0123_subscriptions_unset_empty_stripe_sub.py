"""Unset placeholder stripe_subscription_id="" on pending subscriptions.

Checkout-start used to persist "" before Stripe assigned a real id. The
stripe_sub_unique partial index ({$type: "string"}) covers "", so any later
pending subscription raised DuplicateKeyError and parent autopay start
returned 500. The repository no longer writes ""; this heals existing rows.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0123"


async def up(db: AsyncIOMotorDatabase) -> None:
    await db["subscriptions"].update_many(
        {"stripe_subscription_id": ""},
        {"$unset": {"stripe_subscription_id": ""}},
    )
