"""Lead nurture sends (AI strategy Phase 3, C1).

The claim collection for the nurture sequence's day 2, 7 and 21 steps: one
row per ``(academy_id, subject_id, digest_date)``, where ``subject_id`` is the
``crm_contacts`` id and ``digest_date`` holds the step key
(``nurture:day_<n>``). The unique index is what makes a send idempotent per
(contact, step) across reruns, a second machine and concurrent ticks; rows
also carry ``channel`` (``email`` today, room for C2's SMS). Partial on
``{"subject_id": {"$gt": ""}}``, the planner-usable shape (#878).
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0225_nurture_sends"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["nurture_sends"].create_index(
        [("academy_id", 1), ("subject_id", 1), ("digest_date", 1)],
        unique=True,
        partialFilterExpression={"subject_id": {"$gt": ""}},
        name="nurture_sends_key_unique",
    )
