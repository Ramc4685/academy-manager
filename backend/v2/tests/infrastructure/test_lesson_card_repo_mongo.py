"""End-to-end test of the lesson-card Mongo repos against mongomock.

The unit/seed tests use in-memory fakes; this exercises the real
TenantScopedRepository-backed repos, the 0124 indexes, and the seed use case
through an actual (mock) Mongo driver so the persistence path is covered.
"""

from __future__ import annotations

import importlib

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
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import MongoProgramRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_video_ref_repo import (
    MongoCurriculumVideoRefRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope
from mongomock_motor import AsyncMongoMockClient

ACADEMY_ID = "acad-mongo-test"

_migration = importlib.import_module("backend.v2.migrations.0124_lesson_card_indexes")


async def test_seed_lesson_cards_via_mongo_repos_roundtrip_and_idempotent() -> None:
    db = AsyncMongoMockClient()["lesson_cards_test"]
    await _migration.up(db)

    with tenant_scope(ACADEMY_ID):
        programs = MongoProgramRepository(db)
        levels = MongoLevelRepository(db)
        skills = MongoSkillRepository(db)
        criteria = MongoCriterionRepository(db)
        refs = MongoExternalRefRepository(db)
        cards = MongoLessonCardRepository(db)
        videos = MongoCurriculumVideoRefRepository(db)

        await seed_badminton_pathway(
            academy_id=ACADEMY_ID,
            programs=programs,
            levels=levels,
            skills=skills,
            criteria=criteria,
            refs=refs,
            created_by="admin",
        )

        first = await seed_lesson_cards(
            academy_id=ACADEMY_ID,
            programs=programs,
            levels=levels,
            skills=skills,
            cards=cards,
            video_refs=videos,
            created_by="admin",
        )
        assert first.cards_created == 22
        assert first.video_refs_created == 6

        stored = await cards.list_for_program(first.program_id)
        assert len(stored) == 22
        # display_order is honoured by the query sort.
        assert [c.lesson_number for c in stored] == list(range(1, 23))

        # A skill on the first card resolves back to that card.
        first_card = stored[0]
        for_skill = await cards.list_for_skill(first_card.skill_ids[0])
        assert any(c.slug == first_card.slug for c in for_skill)

        # Reseed is a no-op (no duplicate rows; unique slug index respected).
        second = await seed_lesson_cards(
            academy_id=ACADEMY_ID,
            programs=programs,
            levels=levels,
            skills=skills,
            cards=cards,
            video_refs=videos,
            created_by="admin",
        )
        assert second.cards_created == 0
        assert second.cards_unchanged == 22
        assert second.video_refs_unchanged == 6

        assert await db.lesson_cards.count_documents({}) == 22
        assert await db.curriculum_video_refs.count_documents({}) == 6
