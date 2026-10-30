"""Tap-to-master on a real ``mongod``: tap, undo, evening auto level-up.

Wired exactly as ``composition/pathway.py`` wires it, against the production
indexes and validators (``real_db`` replays every migration). Checks:

* tapping every skill of a level marks them PASSED and queues one level-up;
* undoing a tap drops the skill to PRACTICING and withdraws the queued
  level-up, and re-tapping queues a fresh one;
* the evening sweep moves the student up, issues the certificate, and leaves
  a level that requires owner approval in the owner's queue;
* a skill from another level is refused rather than counted.

Synthetic names only. Skipped without a ``mongod``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.pathway import compose_curriculum, compose_student_progress
from backend.v2.contexts.student_progress.application.use_cases.mark_skill_mastered import (
    MarkSkillMasteredCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevelCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.unmark_skill_mastered import (
    UNDONE_BY_COACH_REASON,
    UnmarkSkillMasteredCommand,
)
from backend.v2.contexts.student_progress.domain.errors import SkillNotOnCurrentLevel
from backend.v2.shared.tenancy import tenant_scope

ACADEMY = "acad-tap"
STUDENT = "stu-tap"
COACH = "coach-tap"


async def _setup(db: Any) -> tuple[Any, str, list[Any]]:
    await db["enrollments"].insert_one(
        {
            "academy_id": ACADEMY,
            "enrollment_id": "enr-tap",
            "session_id": "sess-tap",
            "student_id": STUDENT,
            "status": "active",
            "enrolled_at": datetime(2026, 9, 1, tzinfo=UTC),
        }
    )
    curriculum = compose_curriculum(db)
    progress = compose_student_progress(db)
    program = await curriculum.seed_badminton.execute(created_by="owner")
    levels = sorted(
        await curriculum.list_levels.execute(program.program_id), key=lambda lv: lv.sequence
    )
    await progress.place_student.execute(
        PlaceStudentInLevelCommand(
            student_id=STUDENT,
            program_id=program.program_id,
            level_id=levels[0].level_id,
            placed_by="owner",
        )
    )
    return progress, program.program_id, levels


async def _tap(progress: Any, program_id: str, skill_id: str) -> Any:
    [outcome] = await progress.mark_skill_mastered.execute(
        MarkSkillMasteredCommand(
            skill_id=skill_id, program_id=program_id, student_ids=[STUDENT], coach_id=COACH
        )
    )
    return outcome


async def _display(_rec_id: str) -> dict[str, object]:
    return {"student_name": "Test Player", "level_name": "Level", "program_name": "Pathway"}


@pytest.mark.asyncio
async def test_tap_undo_and_evening_level_up(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        progress, program_id, levels = await _setup(real_db)
        skills = await real_db["skills"].find({"level_id": levels[0].level_id}).to_list(None)
        skill_ids = [s["skill_id"] for s in sorted(skills, key=lambda s: s["sequence"])]

        outcomes = [await _tap(progress, program_id, sid) for sid in skill_ids]
        assert [o.outcome for o in outcomes] == ["mastered"] * len(skill_ids)
        assert [o.level_up_queued for o in outcomes] == [False] * (len(skill_ids) - 1) + [True]
        assert (await _tap(progress, program_id, skill_ids[0])).outcome == "already_mastered"

        # Undo the last tap: skill back to practicing, queued level-up withdrawn.
        undone = await progress.unmark_skill_mastered.execute(
            UnmarkSkillMasteredCommand(
                student_id=STUDENT, skill_id=skill_ids[-1], program_id=program_id, updated_by=COACH
            )
        )
        assert undone.status == "PRACTICING"
        assert len(undone.withdrawn_rec_ids) == 1
        withdrawn = await real_db["level_up_recommendations"].find_one(
            {"rec_id": undone.withdrawn_rec_ids[0]}
        )
        assert withdrawn["status"] == "REJECTED"
        assert withdrawn["rejection_reason"] == UNDONE_BY_COACH_REASON
        # Nothing pending, so the sweep does nothing.
        assert (await progress.auto_approve_level_ups.execute(_display)).approved == 0

        assert (await _tap(progress, program_id, skill_ids[-1])).level_up_queued is True
        run = await progress.auto_approve_level_ups.execute(_display)
        assert (run.approved, run.needs_owner) == (1, 0)

        active = await real_db["student_level_progress"].find_one(
            {"student_id": STUDENT, "status": "active"}
        )
        assert active["level_id"] == levels[1].level_id
        assert await real_db["skill_certificates"].count_documents({"student_id": STUDENT}) == 1

        # A level-1 skill no longer counts, and cannot be undone either.
        assert (await _tap(progress, program_id, skill_ids[0])).outcome == "not_on_level"
        with pytest.raises(SkillNotOnCurrentLevel):
            await progress.unmark_skill_mastered.execute(
                UnmarkSkillMasteredCommand(
                    student_id=STUDENT,
                    skill_id=skill_ids[0],
                    program_id=program_id,
                    updated_by=COACH,
                )
            )


@pytest.mark.asyncio
async def test_level_requiring_owner_approval_stays_in_the_queue(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        progress, program_id, levels = await _setup(real_db)
        await real_db["skill_levels"].update_one(
            {"level_id": levels[0].level_id}, {"$set": {"requires_admin_approval": True}}
        )
        skills = await real_db["skills"].find({"level_id": levels[0].level_id}).to_list(None)
        for skill in skills:
            await _tap(progress, program_id, skill["skill_id"])

        run = await progress.auto_approve_level_ups.execute(_display)
        assert (run.approved, run.needs_owner) == (0, 1)
        pending = await real_db["level_up_recommendations"].find_one({"student_id": STUDENT})
        assert pending["status"] == "RECOMMENDED"
