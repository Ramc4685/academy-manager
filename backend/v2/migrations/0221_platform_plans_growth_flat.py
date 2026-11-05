"""Seed the Growth and Flat ``PlatformPlan`` rows (AI strategy Phase 2, A2).

Growth: $99 a month, ``features: ["ai"]``, 0 bps processing markup. Flat: $49
a month, assigned per academy by the owner through the platform activate
route, never automatically. ``$setOnInsert`` so a row that already exists for
the code is never overwritten; the owner sets ``stripe_price_id`` later via
``PUT /api/v2/platform/billing/plans/{plan_id}``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0221_platform_plans_growth_flat"

PLANS: tuple[dict[str, object], ...] = (
    {
        "plan_id": "plan_growth",
        "code": "growth",
        "display_name": "Growth",
        "monthly_price_cents": 9900,
        "features": ["ai"],
    },
    {
        "plan_id": "plan_flat",
        "code": "flat",
        "display_name": "Flat",
        "monthly_price_cents": 4900,
        "features": [],
    },
)


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    now = datetime.now(UTC)
    for plan in PLANS:
        await db["platform_plans"].update_one(
            {"code": plan["code"]},
            {
                "$setOnInsert": {
                    **plan,
                    "currency": "usd",
                    "limits": {
                        "max_active_students": None,
                        "max_locations": None,
                        "max_staff_members": None,
                    },
                    "status": "active",
                    "stripe_price_id": None,
                    "created_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
