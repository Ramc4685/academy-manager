"""Backfill template_session_id on session_occurrences (D2).

Sets template_session_id = session_id for any occurrence missing the field.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0106_occurrence_template_session_id"


async def up(db: AsyncIOMotorDatabase) -> None:
    await db.session_occurrences.update_many(
        {"template_session_id": {"$exists": False}},
        [{"$set": {"template_session_id": "$session_id"}}],
    )
    await db.session_occurrences.create_index(
        "template_session_id",
        name="session_occurrences_template_session_id",
        sparse=True,
    )
