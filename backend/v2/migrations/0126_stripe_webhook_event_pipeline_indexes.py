"""Indexes for async Stripe webhook event processing."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0126"


async def up(db: AsyncIOMotorDatabase) -> None:
    events = db["stripe_webhook_events"]
    await events.create_index("event_id", unique=True, name="event_id_unique")
    await events.create_index(
        [("status", 1), ("next_retry_at", 1), ("received_at", 1)],
        name="stripe_event_worker_queue",
    )
    await events.create_index(
        [("status", 1), ("processing_locked_until", 1)],
        name="stripe_event_stale_locks",
    )
    await events.create_index(
        [("academy_id", 1), ("status", 1), ("received_at", -1)],
        name="stripe_event_admin_status",
    )

    payments = db["payments"]
    await payments.create_index(
        [("academy_id", 1), ("stripe_invoice_id", 1)],
        unique=True,
        partialFilterExpression={"stripe_invoice_id": {"$type": "string"}},
        name="academy_stripe_invoice_unique",
    )
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

    subscriptions = db["subscriptions"]
    await subscriptions.create_index(
        "stripe_subscription_id",
        unique=True,
        partialFilterExpression={"stripe_subscription_id": {"$type": "string"}},
        name="stripe_sub_unique",
    )

    users = db["users"]
    await users.create_index(
        "stripe_customer_id",
        unique=True,
        partialFilterExpression={"stripe_customer_id": {"$type": "string"}},
        name="stripe_customer_unique",
    )
