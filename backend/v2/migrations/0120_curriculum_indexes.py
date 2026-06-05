"""Curriculum indexes: skill_programs, skill_levels, skills, skill_criteria, external_lesson_refs."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0120"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    # --- skill_programs ---
    programs = db["skill_programs"]
    await programs.create_index(
        [("academy_id", 1), ("is_active", 1)],
        name="programs_by_academy_active",
    )
    await programs.create_index(
        "program_id",
        unique=True,
        name="program_id_unique",
    )

    # --- skill_levels ---
    levels = db["skill_levels"]
    await levels.create_index(
        [("academy_id", 1), ("program_id", 1), ("sequence", 1)],
        unique=True,
        name="levels_academy_program_seq_unique",
    )
    await levels.create_index(
        [("academy_id", 1), ("program_id", 1), ("is_active", 1)],
        name="levels_by_program_active",
    )
    await levels.create_index(
        "level_id",
        unique=True,
        name="level_id_unique",
    )

    # --- skills ---
    skills = db["skills"]
    await skills.create_index(
        [("academy_id", 1), ("level_id", 1), ("sequence", 1)],
        unique=True,
        name="skills_academy_level_seq_unique",
    )
    await skills.create_index(
        [("academy_id", 1), ("program_id", 1), ("is_required", 1)],
        name="skills_by_program_required",
    )
    await skills.create_index(
        "skill_id",
        unique=True,
        name="skill_id_unique",
    )

    # --- skill_criteria ---
    criteria = db["skill_criteria"]
    await criteria.create_index(
        [("academy_id", 1), ("skill_id", 1), ("display_order", 1)],
        name="criteria_by_skill_order",
    )
    await criteria.create_index(
        "criterion_id",
        unique=True,
        name="criterion_id_unique",
    )

    # --- external_lesson_refs ---
    refs = db["external_lesson_refs"]
    await refs.create_index(
        [("academy_id", 1), ("skill_id", 1)],
        name="refs_by_skill",
    )
    await refs.create_index(
        "ref_id",
        unique=True,
        name="ref_id_unique",
    )
