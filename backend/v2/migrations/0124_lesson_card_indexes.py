"""Lesson card + curriculum video reference indexes."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0124"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    # --- lesson_cards ---
    cards = db["lesson_cards"]
    await cards.create_index(
        "card_id",
        unique=True,
        name="lesson_card_id_unique",
    )
    await cards.create_index(
        [("academy_id", 1), ("program_id", 1), ("slug", 1)],
        unique=True,
        name="lesson_cards_academy_program_slug_unique",
    )
    await cards.create_index(
        [("academy_id", 1), ("level_id", 1), ("display_order", 1)],
        name="lesson_cards_by_level_order",
    )
    await cards.create_index(
        [("academy_id", 1), ("skill_ids", 1)],
        name="lesson_cards_by_skill",
    )

    # --- curriculum_video_refs ---
    refs = db["curriculum_video_refs"]
    await refs.create_index(
        "ref_id",
        unique=True,
        name="curriculum_video_ref_id_unique",
    )
    await refs.create_index(
        [
            ("academy_id", 1),
            ("program_id", 1),
            ("scope", 1),
            ("level_id", 1),
            ("skill_id", 1),
            ("url", 1),
        ],
        unique=True,
        name="curriculum_video_refs_identity_unique",
    )
    await refs.create_index(
        [("academy_id", 1), ("skill_id", 1)],
        name="curriculum_video_refs_by_skill",
    )
    await refs.create_index(
        [("academy_id", 1), ("level_id", 1)],
        name="curriculum_video_refs_by_level",
    )
