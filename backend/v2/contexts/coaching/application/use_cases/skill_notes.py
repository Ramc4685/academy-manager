"""Coach skill notes use cases.

Skill notes carry the same ``visibility`` flag as progress notes (private by
default, explicit share with the parent). The assistant rule is identical:
an assistant-only caller may write notes but never share them or change
their visibility (``NoteShareForbidden``, 403). A shared note reaches the
parent's Progress page only when it carries ``shared_at`` (D-15): notes ticked
"shared" before parents could see skill notes have none and stay off the feed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from backend.v2.contexts.coaching.application.ports import SkillNameLookup, SkillNoteRepository
from backend.v2.contexts.coaching.domain.errors import NoteNotFound, NoteShareForbidden
from backend.v2.contexts.coaching.domain.models import CoachSkillNote, NoteVisibility

__all__ = [
    "CreateSkillNote",
    "CreateSkillNoteCommand",
    "ListParentSkillNotes",
    "ListSkillNotes",
    "NoteVisibility",
    "ParentSkillNote",
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
        now = datetime.now(UTC)
        note = CoachSkillNote(
            note_id=str(uuid4()),
            academy_id=academy_id,
            student_id=cmd.student_id,
            skill_id=cmd.skill_id,
            coach_id=cmd.coach_id,
            session_id=cmd.session_id,
            body=cmd.body,
            created_at=now,
            visibility=cmd.visibility,
            shared_at=now if cmd.visibility == "shared" else None,
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
        shared_at = (note.shared_at or datetime.now(UTC)) if cmd.visibility == "shared" else None
        updated = await self._notes.set_visibility(
            cmd.student_id, cmd.note_id, cmd.visibility, shared_at
        )
        if updated is None:
            raise NoteNotFound("note not found", student_id=cmd.student_id, note_id=cmd.note_id)
        return updated


@dataclass(frozen=True)
class ParentSkillNote:
    note_id: str
    skill_id: str
    skill_name: str
    body: str
    shared_at: datetime


class ListParentSkillNotes:
    """The parent's read of a child's shared skill notes. Child ownership is
    the route's job; the coach's id never leaves this use case."""

    LIMIT = 50

    def __init__(self, *, notes: SkillNoteRepository, skills: SkillNameLookup) -> None:
        self._notes = notes
        self._skills = skills

    async def execute(self, student_id: str) -> list[ParentSkillNote]:
        notes = await self._notes.list_shared_with_parent(student_id, self.LIMIT)
        names = await self._skills.names(sorted({n.skill_id for n in notes})) if notes else {}
        return [
            ParentSkillNote(
                note_id=n.note_id,
                skill_id=n.skill_id,
                skill_name=names.get(n.skill_id, "Skill"),
                body=n.body,
                shared_at=n.shared_at,
            )
            for n in notes
            if n.shared_at is not None
        ]
