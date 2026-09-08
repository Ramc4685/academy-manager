"""Coach skill notes use cases.

Skill notes carry the same ``visibility`` flag as progress notes (private by
default, explicit share with the parent). The assistant rule is identical:
an assistant-only caller may write notes but never share them or change
their visibility (``NoteShareForbidden``, 403). Parents do not read skill
notes today; the flag exists for the assistant rule and future parent
surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from backend.v2.contexts.coaching.application.ports import SkillNoteRepository
from backend.v2.contexts.coaching.domain.errors import NoteNotFound, NoteShareForbidden
from backend.v2.contexts.coaching.domain.models import CoachSkillNote, NoteVisibility

__all__ = [
    "CreateSkillNote",
    "CreateSkillNoteCommand",
    "ListSkillNotes",
    "NoteVisibility",
    "SetSkillNoteVisibility",
    "SetSkillNoteVisibilityCommand",
]


@dataclass(frozen=True)
class CreateSkillNoteCommand:
    student_id: str
    skill_id: str
    body: str
    coach_id: str
    session_id: str | None = field(default=None)
    visibility: NoteVisibility = "private"
    is_assistant: bool = False


@dataclass(frozen=True)
class SetSkillNoteVisibilityCommand:
    student_id: str
    note_id: str
    visibility: NoteVisibility
    coach_id: str
    is_assistant: bool = False
    is_supervisor: bool = False


class CreateSkillNote:
    def __init__(self, *, notes: SkillNoteRepository) -> None:
        self._notes = notes

    async def execute(self, cmd: CreateSkillNoteCommand, *, academy_id: str) -> CoachSkillNote:
        if cmd.is_assistant and cmd.visibility == "shared":
            raise NoteShareForbidden(
                "assistant coaches cannot share notes with parents",
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
            )
        note = CoachSkillNote(
            note_id=str(uuid4()),
            academy_id=academy_id,
            student_id=cmd.student_id,
            skill_id=cmd.skill_id,
            coach_id=cmd.coach_id,
            session_id=cmd.session_id,
            body=cmd.body,
            created_at=datetime.now(UTC),
            visibility=cmd.visibility,
        )
        await self._notes.save(note)
        return note


class ListSkillNotes:
    def __init__(self, *, notes: SkillNoteRepository) -> None:
        self._notes = notes

    async def execute(self, student_id: str, skill_id: str) -> list[CoachSkillNote]:
        return await self._notes.list_for_student_skill(student_id, skill_id)


class SetSkillNoteVisibility:
    """Flip a skill note's visibility. Student assignment is the route's job
    (``_require_assigned_to_student``), exactly as it is for create."""

    def __init__(self, *, notes: SkillNoteRepository) -> None:
        self._notes = notes

    async def execute(self, cmd: SetSkillNoteVisibilityCommand) -> CoachSkillNote:
        if cmd.is_assistant:
            raise NoteShareForbidden(
                "assistant coaches cannot change note visibility",
                student_id=cmd.student_id,
                note_id=cmd.note_id,
            )
        note = await self._notes.get(cmd.student_id, cmd.note_id)
        if note is None or (not cmd.is_supervisor and note.coach_id != cmd.coach_id):
            raise NoteNotFound("note not found", student_id=cmd.student_id, note_id=cmd.note_id)
        updated = await self._notes.set_visibility(cmd.student_id, cmd.note_id, cmd.visibility)
        if updated is None:
            raise NoteNotFound("note not found", student_id=cmd.student_id, note_id=cmd.note_id)
        return updated
