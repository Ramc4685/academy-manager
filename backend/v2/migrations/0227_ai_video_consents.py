"""``ai_video_consents`` index (AI strategy Phase 3, slice E1).

One row per child per academy: unique on ``(academy_id, student_id)``, which
also serves the ``consent_ai_video`` read path and the parent's per-child
lookup. Partial on ``{"student_id": {"$gt": ""}}``, the planner-usable shape
(#878). New, empty collection; idempotent.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0227_ai_video_consents"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["ai_video_consents"].create_index(
        [("academy_id", 1), ("student_id", 1)],
        unique=True,
        partialFilterExpression={"student_id": {"$gt": ""}},
        name="ai_video_consents_academy_student_unique",
    )
