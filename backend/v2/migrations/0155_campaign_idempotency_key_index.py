"""Unique idempotency-key index for email campaigns (issue #512).

``SendCampaign.try_claim`` is an insert-first lock against this index: a
retried POST /campaigns with the same (client-supplied or content-derived)
idempotency key hits the duplicate-key error, loses the claim, and re-emails
nothing — mirroring the coach-digest ``try_claim`` guard.

Partial on ``idempotency_key`` being a string so campaigns written before
this change (which lack the field) neither block each other nor the index
build.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0155_campaign_idempotency_key_index"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["message_campaigns"].create_index(
        [("academy_id", 1), ("idempotency_key", 1)],
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
        name="message_campaigns_academy_idempotency_key_unique",
    )
