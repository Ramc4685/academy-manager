"""Student progress indexes: student_level_progress, student_skill_progress, test_attempts."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0121"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    # --- student_level_progress ---
    level_prog = db["student_level_progress"]
    await level_prog.create_index(
        [("academy_id", 1), ("student_id", 1), ("status", 1)],
        name="level_progress_by_student_status",
    )
    await level_prog.create_index(
        [("academy_id", 1), ("student_id", 1), ("program_id", 1)],
        unique=True,
        name="level_progress_active_unique",
        partialFilterExpression={"status": "active"},
    )
    await level_prog.create_index(
        "progress_id",
        unique=True,
        name="level_progress_id_unique",
    )

    # --- student_skill_progress ---
    skill_prog = db["student_skill_progress"]
    await skill_prog.create_index(
        [("academy_id", 1), ("student_id", 1), ("level_id", 1)],
        name="skill_progress_by_student_level",
    )
    await skill_prog.create_index(
        [("academy_id", 1), ("student_id", 1), ("skill_id", 1)],
        unique=True,
        name="skill_progress_student_skill_unique",
    )
    await skill_prog.create_index(
        "skill_progress_id",
        unique=True,
        name="skill_progress_id_unique",
    )

    # --- test_attempts ---
    attempts = db["test_attempts"]
    await attempts.create_index(
        [("academy_id", 1), ("student_id", 1), ("skill_id", 1), ("tested_at", 1)],
        name="attempts_by_student_skill",
    )
    await attempts.create_index(
        [("academy_id", 1), ("coach_id", 1), ("tested_at", -1)],
        name="attempts_by_coach",
    )
    await attempts.create_index(
        [("academy_id", 1), ("session_id", 1)],
        name="attempts_by_session",
        sparse=True,
    )
    await attempts.create_index(
        "attempt_id",
        unique=True,
        name="attempt_id_unique",
    )
