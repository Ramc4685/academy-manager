"""Use case: coach adds, edits or removes the one-line note on a fresh mastery.

The note rides on the PASSED ``student_skill_progress`` row, so the evening
win email and the parent's recent wins read it with the win itself. Undo
clears it (``UnmarkSkillMastered``). The 7 pm email carries whatever note is
there when it sends; later edits only reach the parent's progress page.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from backend.v2.contexts.student_progress.application.ports import StudentSkillProgressRepository
from backend.v2.contexts.student_progress.domain.errors import (
    MasteryNoteClosed,
    SkillProgressNotFound,
)
from backend.v2.contexts.student_progress.domain.models import StudentSkillProgress

MASTERY_NOTE_MAX_CHARS = 140
# shortcut: a rolling day, not the academy-local calendar day; switch to the
# academy timezone if coaches need notes on yesterday's late-evening class.
MASTERY_NOTE_WINDOW = timedelta(hours=24)


class SetMasteryNoteCommand(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    skill_id: str
    #: ``None`` or blank removes the note.
    note: str | None = Field(default=None, max_length=MASTERY_NOTE_MAX_CHARS)
    updated_by: str


class SetMasteryNote:
    def __init__(self, *, skill_progress: StudentSkillProgressRepository) -> None:
        self._skill_progress = skill_progress

    async def execute(self, cmd: SetMasteryNoteCommand) -> StudentSkillProgress:
        row = await self._skill_progress.get(cmd.student_id, cmd.skill_id)
        if row is None or row.status != "PASSED":
            raise SkillProgressNotFound(
                "only a mastered skill can carry a note",
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
            )
        passed_at = row.last_updated_at
        if passed_at.tzinfo is None:
            passed_at = passed_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - passed_at > MASTERY_NOTE_WINDOW:
            raise MasteryNoteClosed(
                "notes can only be added on the day of the win",
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
            )
        note = " ".join((cmd.note or "").split()) or None
        if not await self._skill_progress.set_coach_note(
            cmd.student_id, cmd.skill_id, passed_at=row.last_updated_at, note=note
        ):
            raise SkillProgressNotFound(
                "the win changed (undone or re-marked) while the note was saving",
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
            )
        return row.model_copy(update={"coach_note": note})
