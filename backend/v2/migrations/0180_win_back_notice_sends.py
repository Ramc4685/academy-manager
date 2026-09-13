"""Win-back notice sends (issue #778).

Adds the claim collection for the 30/60/90-day win-back outreach job —
unique on ``(academy_id, student_id, milestone_key)`` so
``claim_digest_send``'s unique-index enforcement (already safe on its own;
see migration 0170's identical note for ``enrollment_hold_notice_sends``)
also keeps the collection from growing unbounded near-duplicate rows under
a stuck or retried job.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0180_win_back_notice_sends"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["win_back_notice_sends"].create_index(
        [("academy_id", 1), ("student_id", 1), ("milestone_key", 1)],
        unique=True,
        name="win_back_notice_sends_key_unique",
    )
