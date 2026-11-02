"""Level colours and the coach's note on a real ``mongod``.

* Seeded levels carry no stored colour and read back the belt-order default;
  the owner's colour is stored per tenant and ``""`` returns to the default.
* The coach note rides on the PASSED mastery row, scoped to the academy:
  another academy cannot see or set it, undo clears it, and an old win or a
  non-mastered skill refuses one.

Synthetic names only. Skipped without a ``mongod``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from backend.v2.composition.pathway import compose_curriculum, compose_student_progress
from backend.v2.contexts.curriculum.application.use_cases.manage_levels import UpdateLevelCommand
from backend.v2.contexts.curriculum.domain.models import DEFAULT_LEVEL_COLORS
from backend.v2.contexts.student_progress.application.use_cases.mark_skill_mastered import (
    MarkSkillMasteredCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevelCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.set_mastery_note import (
    SetMasteryNote,
    SetMasteryNoteCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.unmark_skill_mastered import (
    UnmarkSkillMasteredCommand,
)
from backend.v2.contexts.student_progress.domain.errors import (
    MasteryNoteClosed,
    SkillProgressNotFound,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-colour"
OTHER = "acad-colour-other"
STUDENT = "stu-colour"
COACH = "coach-colour"


async def _seed(db: Any) -> tuple[Any, Any, str, list[Any]]:
    await db["enrollments"].insert_one(
        {
            "academy_id": ACADEMY,
            "enrollment_id": "enr-colour",
            "session_id": "sess-colour",
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
    return curriculum, progress, program.program_id, levels


async def test_levels_default_to_belt_colours_and_owner_can_change_one(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        curriculum, _progress, program_id, levels = await _seed(real_db)
        assert [lv.color for lv in levels] == [None] * len(levels)
        assert [lv.display_color for lv in levels[:6]] == [hex_ for _, hex_ in DEFAULT_LEVEL_COLORS]
        stored = await real_db["skill_levels"].find_one({"level_id": levels[1].level_id})
        assert "color" not in stored or stored["color"] is None  # nothing backfilled

        updated = await curriculum.update_level.execute(
            UpdateLevelCommand(level_id=levels[1].level_id, color="#0ea5e9", updated_by="owner")
        )
        assert (updated.color, updated.display_color) == ("#0EA5E9", "#0EA5E9")
        reread = await curriculum.list_levels.execute(program_id)
        assert reread[1].display_color == "#0EA5E9"
        assert reread[0].display_color == DEFAULT_LEVEL_COLORS[0][1]

        reset = await curriculum.update_level.execute(
            UpdateLevelCommand(level_id=levels[1].level_id, color="", updated_by="owner")
        )
        assert (reset.color, reset.display_color) == (None, DEFAULT_LEVEL_COLORS[1][1])

    with pytest.raises(ValidationError):
        UpdateLevelCommand(level_id="x", color="red", updated_by="owner")

    # Another academy never sees (or recolours) this tenant's level.
    with tenant_scope(OTHER):
        assert await compose_curriculum(real_db).list_levels.execute(program_id) == []


async def test_coach_note_is_tenant_scoped_cleared_on_undo_and_only_on_fresh_wins(
    real_db: Any,
) -> None:
    with tenant_scope(ACADEMY):
        _curriculum, progress, program_id, levels = await _seed(real_db)
        skills = await real_db["skills"].find({"level_id": levels[0].level_id}).to_list(None)
        first, second = (s["skill_id"] for s in sorted(skills, key=lambda s: s["sequence"])[:2])

        await progress.mark_skill_mastered.execute(
            MarkSkillMasteredCommand(
                skill_id=first, program_id=program_id, student_ids=[STUDENT], coach_id=COACH
            )
        )
        row = await progress.set_mastery_note.execute(
            SetMasteryNoteCommand(
                student_id=STUDENT,
                skill_id=first,
                note="  Much quicker\nto the net  ",
                updated_by=COACH,
            )
        )
        assert row.coach_note == "Much quicker to the net"
        doc = await real_db["student_skill_progress"].find_one({"skill_id": first})
        assert (doc["academy_id"], doc["coach_note"], doc["status"]) == (
            ACADEMY,
            "Much quicker to the net",
            "PASSED",
        )

        # Not mastered yet: no note.
        with pytest.raises(SkillProgressNotFound):
            await progress.set_mastery_note.execute(
                SetMasteryNoteCommand(
                    student_id=STUDENT, skill_id=second, note="hi", updated_by=COACH
                )
            )

    # The other academy cannot reach this tenant's mastery row.
    with tenant_scope(OTHER):
        with pytest.raises(SkillProgressNotFound):
            await compose_student_progress(real_db).set_mastery_note.execute(
                SetMasteryNoteCommand(
                    student_id=STUDENT, skill_id=first, note="hijack", updated_by="x"
                )
            )

    with tenant_scope(ACADEMY):
        assert (await real_db["student_skill_progress"].find_one({"skill_id": first}))[
            "coach_note"
        ] == "Much quicker to the net"

        # Blank removes it.
        removed = await progress.set_mastery_note.execute(
            SetMasteryNoteCommand(student_id=STUDENT, skill_id=first, note="  ", updated_by=COACH)
        )
        assert removed.coach_note is None

        # Undo clears the note so a re-tap starts clean.
        await progress.set_mastery_note.execute(
            SetMasteryNoteCommand(student_id=STUDENT, skill_id=first, note="Nice", updated_by=COACH)
        )
        await progress.unmark_skill_mastered.execute(
            UnmarkSkillMasteredCommand(
                student_id=STUDENT, skill_id=first, program_id=program_id, updated_by=COACH
            )
        )
        doc = await real_db["student_skill_progress"].find_one({"skill_id": first})
        assert (doc["status"], doc["coach_note"]) == ("PRACTICING", None)

        # A win from two days ago is closed for notes.
        await progress.mark_skill_mastered.execute(
            MarkSkillMasteredCommand(
                skill_id=first, program_id=program_id, student_ids=[STUDENT], coach_id=COACH
            )
        )
        await real_db["student_skill_progress"].update_one(
            {"skill_id": first},
            {"$set": {"last_updated_at": datetime.now(UTC) - timedelta(days=2)}},
        )
        with pytest.raises(MasteryNoteClosed):
            await progress.set_mastery_note.execute(
                SetMasteryNoteCommand(
                    student_id=STUDENT, skill_id=first, note="late", updated_by=COACH
                )
            )

    with pytest.raises(ValidationError):
        SetMasteryNoteCommand(student_id=STUDENT, skill_id=first, note="x" * 141, updated_by=COACH)


async def test_a_note_saved_after_an_undo_does_not_bring_the_win_back(real_db: Any) -> None:
    """Undo lands between the note's read and its write: the note must not
    restore the PASSED row (only ``coach_note`` is written, on the same pass)."""
    with tenant_scope(ACADEMY):
        _curriculum, progress, program_id, levels = await _seed(real_db)
        skill = (await real_db["skills"].find_one({"level_id": levels[0].level_id}))["skill_id"]
        await progress.mark_skill_mastered.execute(
            MarkSkillMasteredCommand(
                skill_id=skill, program_id=program_id, student_ids=[STUDENT], coach_id=COACH
            )
        )
        repo = MongoStudentSkillProgressRepository(real_db)
        stale = await repo.get(STUDENT, skill)
        await progress.unmark_skill_mastered.execute(
            UnmarkSkillMasteredCommand(
                student_id=STUDENT, skill_id=skill, program_id=program_id, updated_by=COACH
            )
        )

        class _ReadBeforeUndo:
            async def get(self, *_: Any) -> Any:
                return stale

            set_coach_note = repo.set_coach_note

        with pytest.raises(SkillProgressNotFound):
            await SetMasteryNote(skill_progress=_ReadBeforeUndo()).execute(  # type: ignore[arg-type]
                SetMasteryNoteCommand(
                    student_id=STUDENT, skill_id=skill, note="Nice", updated_by=COACH
                )
            )
        doc = await real_db["student_skill_progress"].find_one({"skill_id": skill})
        assert (doc["status"], doc["coach_note"]) == ("PRACTICING", None)
