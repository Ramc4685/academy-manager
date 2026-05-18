"""Billing indexes per plan §0.7."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0030"


async def _unique_optional_string(collection, field: str, name: str) -> None:
    await collection.update_many({field: None}, {"$unset": {field: ""}})
    await collection.create_index(
        field,
        unique=True,
        name=name,
        sparse=True,
    )


async def _has_index_with_key(collection, key: list[tuple[str, int]]) -> bool:
    indexes = await collection.index_information()
    return any(info.get("key") == key for info in indexes.values())


async def up(db: AsyncIOMotorDatabase) -> None:
    payments = db["payments"]
    await _unique_optional_string(payments, "payment_id", "payment_id_unique")
    await payments.create_index(
        [("academy_id", 1), ("stripe_payment_intent_id", 1)],
        unique=True,
        partialFilterExpression={"stripe_payment_intent_id": {"$type": "string"}},
        name="academy_stripe_pi_unique",
    )
    await payments.create_index(
        [("academy_id", 1), ("stripe_checkout_session_id", 1)],
        unique=True,
        partialFilterExpression={"stripe_checkout_session_id": {"$type": "string"}},
        name="academy_checkout_session_unique",
    )
    await payments.create_index(
        [("academy_id", 1), ("parent_id", 1), ("created_at", -1)],
        name="parent_history",
    )

    subs = db["subscriptions"]
    await _unique_optional_string(subs, "subscription_id", "subscription_id_unique")
    await subs.create_index(
        "stripe_subscription_id",
        unique=True,
        name="stripe_sub_unique",
        partialFilterExpression={"stripe_subscription_id": {"$type": "string"}},
    )
    await subs.create_index(
        [("academy_id", 1), ("parent_id", 1)],
        name="parent_subscriptions",
    )

    events = db["stripe_webhook_events"]
    if not await _has_index_with_key(events, [("event_id", 1)]):
        await events.create_index("event_id", unique=True, name="event_id_unique")
    if not await _has_index_with_key(events, [("received_at", 1)]):
        await events.create_index("received_at", name="received_at")
