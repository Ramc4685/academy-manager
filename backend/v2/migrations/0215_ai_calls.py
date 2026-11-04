"""``ai_calls`` audit indexes (AI foundation, plan section 4 Phase 1).

``(academy_id, created_at)`` serves the monthly cap count and
``(academy_id, feature, created_at)`` the per-feature usage read.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0215_ai_calls"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    calls = db["ai_calls"]
    await calls.create_index(
        [("academy_id", 1), ("created_at", 1)],
        name="ai_calls_academy_created",
    )
    await calls.create_index(
        [("academy_id", 1), ("feature", 1), ("created_at", 1)],
        name="ai_calls_academy_feature_created",
    )
