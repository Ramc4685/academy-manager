"""Phase 1 portal enrichment indexes.

Session feedback (coach-authored per-student notes with optional rating)
and invoice parent query index.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0112_phase1_portal"


async def up(db: AsyncIOMotorDatabase) -> None:
    feedback = db["session_feedback"]
    await feedback.create_index(
        "feedback_id",
        unique=True,
        sparse=True,
        name="session_feedback_id_unique",
    )
    await feedback.create_index(
        [("academy_id", 1), ("session_id", 1)],
        name="session_feedback_academy_session",
    )
    await feedback.create_index(
        [("academy_id", 1), ("student_id", 1), ("created_at", -1)],
        name="session_feedback_academy_student_time",
    )

    invoices = db["invoices"]
    await invoices.create_index(
        [("academy_id", 1), ("parent_id", 1), ("created_at", -1)],
        name="invoices_academy_parent_time",
    )
