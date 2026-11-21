"""Retire and reorder levels and skills over a REAL mongod (lane L5, slice A4).

Real Mongo because reorder leans on the unique sequence indexes from 0120.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.contexts.curriculum.application.errors import (
    DuplicateSequence,
    InvalidOrder,
    LevelNotFound,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_levels import (
    CreateLevel,
    CreateLevelCommand,
    ReorderLevels,
)
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
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpCommand,
)
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.tests.contract.test_curriculum_placement_real_mongo import (
    ACADEMY,
    AT,
    _Live,
    _pass,
    _place,
    _rec,
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
                    level_id="OTHER", program_id="prog", name="X", created_by="owner"
                )
            )


def _checks(w: dict[str, Any]) -> CurriculumChangeChecks:
    return CurriculumChangeChecks(
        level_progress=w["level_progress"],
        skill_progress=w["skill_progress"],
        skill_lookup=w["lookup"],
        recommendations=w["recs"],
        recommend_level_up=RecommendLevelUp(
            level_progress=w["level_progress"],
            skill_progress=w["skill_progress"],
            recommendations=w["recs"],
            skill_lookup=w["lookup"],
            enrollment_lookup=_Live(),
        ),
    )


async def _retire(db: Any, w: dict[str, Any], skill_id: str) -> int:
    """What the admin route does: read who is held back, retire, recheck them."""
    checks = _checks(w)
    held_back = await checks.held_back_by(skill_id)
    skill = await UpdateSkill(skills=MongoSkillRepository(db)).execute(
        UpdateSkillCommand(skill_id=skill_id, is_active=False, updated_by="owner")
    )
    return await checks.recheck_students(skill.level_id, held_back, "owner")


async def test_retiring_the_skill_holding_a_student_back_queues_the_level_up(
    real_db: Any,
) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _pass(w, "s1")
        on_level = await _checks(w).active_student_ids("L1")
        queued = await _retire(real_db, w, "s2")
        pending = await _checks(w).has_pending_level_ups("prog")

    assert on_level == ["kid"]
    assert queued == 1 and pending is True


async def test_retiring_a_skill_never_requeues_a_rejected_level_up(real_db: Any) -> None:
    """The kid passed the skill being retired; the owner already said no."""
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _pass(w, "s1")
        await _pass(w, "s2")
        await _rec(w, status="REJECTED")
        queued = await _retire(real_db, w, "s2")
        pending = await _checks(w).has_pending_level_ups("prog")

    assert queued == 0 and pending is False


async def test_retiring_an_optional_skill_queues_nobody(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    await real_db["skills"].update_one({"skill_id": "s2"}, {"$set": {"is_required": False}})
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _pass(w, "s1")
        await _rec(w, status="REJECTED")
        queued = await _retire(real_db, w, "s2")

    assert queued == 0


async def test_retiring_a_skill_twice_queues_nobody_the_second_time(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _pass(w, "s1")
        first = await _retire(real_db, w, "s2")
        rec = await w["recs"].get_active_for_student("kid", "prog")
        assert rec is not None
        await w["review"].execute(
            ReviewLevelUpCommand(rec_id=rec.rec_id, action="reject", reviewed_by="owner")
        )
        second = await _retire(real_db, w, "s2")
        pending = await _checks(w).has_pending_level_ups("prog")

    assert (first, second) == (1, 0)
    assert pending is False


async def test_new_levels_and_skills_number_past_retired_rows(real_db: Any) -> None:
    """The UI used to send levels.length + 1, which collided with a retired row."""
    await _seed_curriculum(real_db)
    await real_db["programs"].insert_one({"academy_id": ACADEMY, "program_id": "prog", "name": "P"})
    with tenant_scope(ACADEMY):
        levels, skills = MongoLevelRepository(real_db), MongoSkillRepository(real_db)
        await UpdateSkill(skills=skills).execute(
            UpdateSkillCommand(skill_id="s2", is_active=False, updated_by="owner")
        )
        level = await CreateLevel(programs=_Programs(), levels=levels).execute(
            CreateLevelCommand(program_id="prog", name="Four", created_by="owner")
        )
        skill = await CreateSkill(levels=levels, skills=skills).execute(
            CreateSkillCommand(level_id="L1", program_id="prog", name="Drop", created_by="owner")
        )
        taken = level.model_copy(update={"level_id": "dup", "name": "Clash"})
        with pytest.raises(DuplicateSequence):
            await levels.save(taken)

    assert level.sequence == 4  # L1=1, L2 (retired)=2, L3=3
    assert skill.sequence == 3  # s1=1, s2 (retired)=2


class _Programs:
    async def get(self, program_id: str) -> object:
        return {"program_id": program_id}


async def test_a_reorder_left_half_done_does_not_wedge_the_next_one(real_db: Any) -> None:
    """A crash after pass one left L1 at 10001; a fixed +10000 lift collided forever."""
    await _seed_curriculum(real_db)
    await real_db["skill_levels"].update_one({"level_id": "L1"}, {"$set": {"sequence": 10001}})
    with tenant_scope(ACADEMY):
        await ReorderLevels(levels=MongoLevelRepository(real_db)).execute("prog", ["L3", "L1"])

    assert await _sequences(real_db, "skill_levels", "level_id", program_id="prog") == [
        ("L3", 1),
        ("L1", 2),
        ("L2", 3),
    ]


async def test_a_level_a_pending_level_up_targets_counts_as_in_use(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        checks = CurriculumChangeChecks(
            level_progress=w["level_progress"],
            skill_progress=w["skill_progress"],
            skill_lookup=w["lookup"],
            recommendations=w["recs"],
            recommend_level_up=None,  # type: ignore[arg-type]
        )
        await w["place"].execute(_place("L1"))
        await _rec(w)  # L1 -> L3, waiting for the evening auto-approve
        into_l3 = await checks.pending_level_ups_into("L3")
        into_l1 = await checks.pending_level_ups_into("L1")

    assert (into_l3, into_l1) == (1, 0)


async def test_a_reorder_racing_a_create_is_a_409_not_a_500(real_db: Any) -> None:
    """A create lands on the number pass one is about to lift a level to."""
    await _seed_curriculum(real_db)
    await real_db["skill_levels"].insert_one(
        {
            "academy_id": ACADEMY,
            "program_id": "prog",
            "level_id": "L9",
            "sequence": 4,
            "name": "Racer",
            "is_active": True,
            "created_at": AT,
            "updated_at": AT,
        }
    )
    with tenant_scope(ACADEMY), pytest.raises(DuplicateSequence):
        # Lift is max(L1, L3) + 1 = 4, which L9 already holds.
        await MongoLevelRepository(real_db).resequence(["L3", "L1"])
