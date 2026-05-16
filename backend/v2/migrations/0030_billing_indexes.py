"""Billing indexes per plan §0.7."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0030"


async def up(db: AsyncIOMotorDatabase) -> None:
    payments = db["payments"]
    await payments.create_index("payment_id", unique=True, name="payment_id_unique")
    await payments.create_index(
        [("academy_id", 1), ("stripe_payment_intent_id", 1)],
        unique=True,
        sparse=True,
        name="academy_stripe_pi_unique",
    )
    await payments.create_index(
        [("academy_id", 1), ("stripe_checkout_session_id", 1)],
        unique=True,
        sparse=True,
        name="academy_checkout_session_unique",
    )
    await payments.create_index(
        [("academy_id", 1), ("parent_id", 1), ("created_at", -1)],
        name="parent_history",
    )

    subs = db["subscriptions"]
    await subs.create_index("subscription_id", unique=True, name="subscription_id_unique")
    await subs.create_index(
        "stripe_subscription_id", unique=True, name="stripe_sub_unique"
    )
    await subs.create_index(
        [("academy_id", 1), ("parent_id", 1)],
        name="parent_subscriptions",
    )

    events = db["stripe_webhook_events"]
    await events.create_index("event_id", unique=True, name="event_id_unique")
    await events.create_index("received_at", name="received_at")
