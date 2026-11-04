"""Trial nudge sends (AI strategy Phase 1, item 3).

The claim collection for the three templated nudge jobs (trial reminder,
no-show follow-up, checkout recovery): unique on ``(academy_id, subject_id,
digest_date)``, where ``subject_id`` is the trial request or application and
``digest_date`` holds the nudge key. ``claim_digest_send`` is safe without
the index (see migration 0170's note); the index keeps a stuck or retried
job from growing near-duplicate rows and serves the claim lookup. Partial on
``{"subject_id": {"$gt": ""}}``, the planner-usable shape (#878).
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0219_trial_nudge_sends"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["trial_nudge_sends"].create_index(
        [("academy_id", 1), ("subject_id", 1), ("digest_date", 1)],
        unique=True,
        partialFilterExpression={"subject_id": {"$gt": ""}},
        name="trial_nudge_sends_key_unique",
    )
