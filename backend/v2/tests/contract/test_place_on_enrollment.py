"""D-10: enrolling a child places them on a pathway level (S51).

``PlaceOnEnrollment`` as ``composition/pathway.py`` wires it, over the
mongomock ``db`` (a real mongod when ``CONTRACT_TESTS_MONGO_URL`` is set).
Synthetic names only.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.composition.pathway import (
    ENROLLMENT_PLACEMENT_REASON,
    compose_curriculum,
    compose_place_on_enrollment,
)
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-d10"


async def _student(db: Any, student_id: str) -> None:
    await db["students"].insert_one(
        {"academy_id": ACADEMY, "student_id": student_id, "parent_id": "p", "full_name": "Kid"}
    )


async def _levels(db: Any) -> list[Any]:
    curriculum = compose_curriculum(db)
    program = await curriculum.seed_badminton.execute(created_by="owner")
    return await curriculum.list_levels.execute(program.program_id)


async def _active_level(db: Any, student_id: str) -> str | None:
    row = await db["student_level_progress"].find_one(
        {"academy_id": ACADEMY, "student_id": student_id, "status": "active"}
    )
    return row["level_id"] if row else None


async def test_new_child_starts_on_the_first_level_or_the_chosen_one(db: Any) -> None:
    with tenant_scope(ACADEMY):
        levels = await _levels(db)
        await _student(db, "stu-1")
        await _student(db, "stu-2")
        placement = compose_place_on_enrollment(db)

        await placement.place_new_enrollee("stu-1", actor_id="admin-1")
        await placement.place_new_enrollee("stu-2", level_id=levels[1].level_id)

        assert await _active_level(db, "stu-1") == levels[0].level_id
        assert await _active_level(db, "stu-2") == levels[1].level_id
        # Level 1's skills are on the board straight away.
        assert await db["student_skill_progress"].count_documents({"student_id": "stu-1"}) > 0
        audit = await db["audit_logs"].find_one(
            {"action": "student.pathway_placed", "entity_id": "stu-1"}
        )
        assert audit["reason"] == ENROLLMENT_PLACEMENT_REASON
        assert audit["actor_id"] == "admin-1"


async def test_a_child_already_on_a_level_keeps_it(db: Any) -> None:
    with tenant_scope(ACADEMY):
        levels = await _levels(db)
        await _student(db, "stu-1")
        placement = compose_place_on_enrollment(db)
        await placement.place_new_enrollee("stu-1", level_id=levels[2].level_id)

        # A second class, or an approval replay, never moves them.
        await placement.place_new_enrollee("stu-1")
        await placement.place_new_enrollee("stu-1", level_id=levels[0].level_id)

        assert await _active_level(db, "stu-1") == levels[2].level_id
        assert await db["student_level_progress"].count_documents({"student_id": "stu-1"}) == 1


async def test_an_academy_without_a_pathway_is_skipped(db: Any) -> None:
    with tenant_scope(ACADEMY):
        await _student(db, "stu-1")
        await compose_place_on_enrollment(db).place_new_enrollee("stu-1")

        assert await _active_level(db, "stu-1") is None
