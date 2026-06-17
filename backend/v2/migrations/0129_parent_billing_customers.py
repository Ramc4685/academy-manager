"""Tenant-scoped parent Stripe customer storage."""

from __future__ import annotations

from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0129"


async def up(db: AsyncIOMotorDatabase) -> None:
    subscriptions = db["subscriptions"]
    await subscriptions.create_index(
        [("academy_id", 1), ("stripe_checkout_session_id", 1)],
        unique=True,
        partialFilterExpression={"stripe_checkout_session_id": {"$type": "string"}},
        name="academy_subscription_checkout_session_unique",
    )
    await subscriptions.create_index(
        [("academy_id", 1), ("parent_id", 1), ("status", 1)],
        name="academy_parent_subscription_status",
    )
    await subscriptions.create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("created_at", -1)],
        name="academy_enrollment_subscription_created",
    )

    customers = db["parent_billing_customers"]
    await customers.create_index(
        [("academy_id", 1), ("parent_id", 1)],
        unique=True,
        name="academy_parent_billing_customer_unique",
    )
    await customers.create_index(
        [("academy_id", 1), ("stripe_customer_id", 1)],
        unique=True,
        partialFilterExpression={"stripe_customer_id": {"$type": "string"}},
        name="academy_stripe_customer_unique",
    )

    now = datetime.now(UTC)
    cursor = db["users"].find(
        {
            "academy_id": {"$type": "string"},
            "user_id": {"$type": "string"},
            "stripe_customer_id": {"$type": "string"},
        },
        {"academy_id": 1, "user_id": 1, "stripe_customer_id": 1},
    )
    async for user in cursor:
        await customers.update_one(
            {"academy_id": user["academy_id"], "parent_id": user["user_id"]},
            {
                "$set": {
                    "stripe_customer_id": user["stripe_customer_id"],
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "academy_id": user["academy_id"],
                    "parent_id": user["user_id"],
                    "created_at": now,
                },
            },
            upsert=True,
        )
