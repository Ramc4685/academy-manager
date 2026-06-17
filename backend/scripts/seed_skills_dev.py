"""Standalone dev script: seeds the badminton skill pathway and lesson cards for academy 'blno'.

Run from repo root:
    python3 backend/scripts/seed_skills_dev.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from motor.motor_asyncio import AsyncIOMotorClient

from backend.v2.contexts.curriculum.application.use_cases.seed_curriculum import (
    seed_badminton_pathway,
)
from backend.v2.contexts.curriculum.application.use_cases.seed_lesson_cards import (
    seed_lesson_cards,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_ext_ref_repo import (
    MongoExternalRefRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_lesson_card_repo import (
    MongoLessonCardRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import (
    MongoLevelRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import (
    MongoProgramRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import (
    MongoSkillRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_video_ref_repo import (
    MongoCurriculumVideoRefRepository,
)
from backend.v2.shared.tenancy import tenant_scope

MONGO_URL = (
    os.environ.get("MONGO_URL")
    or os.environ.get("V2_MONGO_URL")
    or "mongodb://localhost:27017"
)
MONGO_DB = (
    os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB") or "academy_manager"
)
ACADEMY_ID = os.environ.get("SEED_ACADEMY_ID", "blno")


async def main() -> None:
    client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URL)
    db = client[MONGO_DB]

    try:
        programs = MongoProgramRepository(db)
        levels = MongoLevelRepository(db)
        skills = MongoSkillRepository(db)

        with tenant_scope(ACADEMY_ID):
            print(f"Seeding badminton skill pathway for academy '{ACADEMY_ID}' ...")
            await seed_badminton_pathway(
                academy_id=ACADEMY_ID,
                programs=programs,
                levels=levels,
                skills=skills,
                criteria=MongoCriterionRepository(db),
                refs=MongoExternalRefRepository(db),
                created_by="seed-script",
            )
            print("  ✓ Skill pathway seeded.")

            print("Seeding lesson cards ...")
            await seed_lesson_cards(
                academy_id=ACADEMY_ID,
                programs=programs,
                levels=levels,
                skills=skills,
                cards=MongoLessonCardRepository(db),
                video_refs=MongoCurriculumVideoRefRepository(db),
                created_by="seed-script",
            )
            print("  ✓ Lesson cards seeded.")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
