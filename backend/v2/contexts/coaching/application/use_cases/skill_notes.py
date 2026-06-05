"""Coach skill notes use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from backend.v2.contexts.coaching.application.ports import SkillNoteRepository
from backend.v2.contexts.coaching.domain.models import CoachSkillNote


@dataclass(frozen=True)
class CreateSkillNoteCommand:
    student_id: str
    skill_id: str
    body: str
    coach_id: str
    session_id: str | None = field(default=None)


class CreateSkillNote:
    def __init__(self, *, notes: SkillNoteRepository) -> None:
        self._notes = notes

    async def execute(self, cmd: CreateSkillNoteCommand, *, academy_id: str) -> CoachSkillNote:
        note = CoachSkillNote(
            note_id=str(uuid4()),
            academy_id=academy_id,
            student_id=cmd.student_id,
            skill_id=cmd.skill_id,
            coach_id=cmd.coach_id,
            session_id=cmd.session_id,
            body=cmd.body,
            created_at=datetime.now(UTC),
        )
        await self._notes.save(note)
        return note


class ListSkillNotes:
    def __init__(self, *, notes: SkillNoteRepository) -> None:
        self._notes = notes

    async def execute(self, student_id: str, skill_id: str) -> list[CoachSkillNote]:
        return await self._notes.list_for_student_skill(student_id, skill_id)
