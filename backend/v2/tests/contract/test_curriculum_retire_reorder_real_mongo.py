"""Retire and reorder levels and skills over a REAL mongod (lane L5, slice A4).

Real Mongo because reorder leans on the unique sequence indexes from 0120.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.contexts.curriculum.application.errors import InvalidOrder, LevelNotFound
from backend.v2.contexts.curriculum.application.use_cases.manage_levels import ReorderLevels
from backend.v2.contexts.curriculum.application.use_cases.manage_skills import (
    CreateSkill,
    CreateSkillCommand,
    ReorderSkills,
    UpdateSkill,
    UpdateSkillCommand,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.student_progress.application.use_cases.curriculum_change_checks import (
    CurriculumChangeChecks,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
)
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.tests.contract.test_curriculum_placement_real_mongo import (
    ACADEMY,
    _Live,
    _pass,
    _place,
    _seed_curriculum,
    _wire,
)

pytestmark = pytest.mark.asyncio


async def _sequences(db: Any, collection: str, key: str, **filter_: str) -> list[tuple[str, int]]:
    cursor = db[collection].find(filter_).sort("sequence", 1)
    return [(doc[key], doc["sequence"]) async for doc in cursor]


async def test_reorder_levels_renumbers_active_then_retired(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        reorder = ReorderLevels(levels=MongoLevelRepository(real_db))
        await reorder.execute("prog", ["L3", "L1"])
        with pytest.raises(InvalidOrder):
            await reorder.execute("prog", ["L3"])  # missing an active level
        with pytest.raises(InvalidOrder):
            await reorder.execute("prog", ["L3", "L1", "L2"])  # L2 is retired

    assert await _sequences(real_db, "skill_levels", "level_id", program_id="prog") == [
        ("L3", 1),
        ("L1", 2),
        ("L2", 3),
    ]


async def test_reorder_skills_swaps_on_the_unique_index(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        await ReorderSkills(skills=MongoSkillRepository(real_db)).execute("L1", ["s2", "s1"])

    assert await _sequences(real_db, "skills", "skill_id", level_id="L1") == [
        ("s2", 1),
        ("s1", 2),
    ]


async def test_create_skill_refuses_a_level_from_another_program(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        create = CreateSkill(
            levels=MongoLevelRepository(real_db), skills=MongoSkillRepository(real_db)
        )
        with pytest.raises(LevelNotFound):
            await create.execute(
                CreateSkillCommand(
                    level_id="OTHER", program_id="prog", sequence=9, name="X", created_by="owner"
                )
            )


async def test_retiring_the_skill_holding_a_student_back_queues_the_level_up(
    real_db: Any,
) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        checks = CurriculumChangeChecks(
            level_progress=w["level_progress"],
            recommendations=w["recs"],
            recommend_level_up=RecommendLevelUp(
                level_progress=w["level_progress"],
                skill_progress=w["skill_progress"],
                recommendations=w["recs"],
                skill_lookup=w["lookup"],
                enrollment_lookup=_Live(),
            ),
        )
        await w["place"].execute(_place("L1"))
        await _pass(w, "s1")
        on_level = await checks.active_student_ids("L1")
        assert await checks.recheck_level("L1", "owner") == 0  # s2 still open
        await UpdateSkill(skills=MongoSkillRepository(real_db)).execute(
            UpdateSkillCommand(skill_id="s2", is_active=False, updated_by="owner")
        )
        queued = await checks.recheck_level("L1", "owner")
        pending = await checks.has_pending_level_ups("prog")

    assert on_level == ["kid"]
    assert queued == 1 and pending is True
