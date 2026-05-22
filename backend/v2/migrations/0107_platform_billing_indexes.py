"""Platform billing indexes.

Platform billing is tenant SaaS billing. It intentionally uses platform-owned
collections instead of the parent tuition billing collections.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0107_platform_billing_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    plans = db["platform_plans"]
    await plans.create_index(
        "plan_id",
        unique=True,
        name="platform_plans_plan_id_unique",
    )
    await plans.create_index(
        "code",
        unique=True,
        name="platform_plans_code_unique",
    )
    await plans.create_index(
        [("status", 1), ("code", 1)],
        name="platform_plans_status_code",
    )

    subscriptions = db["platform_tenant_subscriptions"]
    await subscriptions.create_index(
        "subscription_id",
        unique=True,
        name="platform_tenant_subscriptions_id_unique",
    )
    await subscriptions.create_index(
        "academy_id",
        unique=True,
        name="platform_tenant_subscriptions_academy_unique",
    )
    await subscriptions.create_index(
        "stripe_customer_id",
        name="platform_tenant_subscriptions_stripe_customer",
        sparse=True,
    )
    await subscriptions.create_index(
        "stripe_subscription_id",
        unique=True,
        name="platform_tenant_subscriptions_stripe_subscription_unique",
        sparse=True,
    )
    await subscriptions.create_index(
        [("billing_status", 1), ("updated_at", -1)],
        name="platform_tenant_subscriptions_status_updated",
    )
