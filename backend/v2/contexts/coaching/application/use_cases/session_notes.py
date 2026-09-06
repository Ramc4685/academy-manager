"""Coach lesson plans and progress notes.

Progress notes carry a ``visibility`` flag (spec
``2026-09-04-role-model-and-screens-design.md``, item 6): private by default,
explicitly shared with the parent. An assistant-only coach may write notes
but never share them — ``visibility="shared"`` on create, or any visibility
change, is refused with :class:`NoteShareForbidden` (403). After creation the
flag can be flipped by the note's author or by a coach supervisor
(owner/admin); anyone else gets :class:`NoteNotFound` (404), because the note
is not theirs to see.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.coaching.domain.errors import (
    NoteNotFound,
    NoteShareForbidden,
    SessionNotAssigned,
    StudentNotEnrolled,
)
from backend.v2.contexts.coaching.domain.models import NoteVisibility
from backend.v2.shared.ids import new_ulid

__all__ = [
    "ActiveEnrollmentLookup",
    "CoachSessionLookup",
    "CoachingNotesRepository",
    "CreateLessonPlan",
    "CreateLessonPlanCommand",
    "CreateProgressNote",
    "CreateProgressNoteCommand",
    "LessonPlan",
    "ListLessonPlans",
    "ListProgressNotes",
    "NoteVisibility",
    "ProgressNote",
    "SetProgressNoteVisibility",
    "SetProgressNoteVisibilityCommand",
]


class LessonPlan(BaseModel):
    model_config = {"frozen": True}

    lesson_plan_id: str
    session_id: str
    coach_id: str
    title: str
    body: str
    created_at: datetime


class ProgressNote(BaseModel):
    model_config = {"frozen": True}

    note_id: str
    session_id: str
    student_id: str
    coach_id: str
    body: str
    created_at: datetime
    visibility: NoteVisibility = "private"


class CoachSessionLookup(Protocol):
    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool: ...


class ActiveEnrollmentLookup(Protocol):
    async def is_active(self, session_id: str, student_id: str) -> bool: ...


class CoachingNotesRepository(Protocol):
    async def add_lesson_plan(self, plan: LessonPlan) -> None: ...
    async def list_lesson_plans(self, session_id: str, coach_id: str) -> list[LessonPlan]: ...
    async def add_progress_note(self, note: ProgressNote) -> None: ...

    async def list_progress_notes(
        self, session_id: str, coach_id: str | None
    ) -> list[ProgressNote]:
        """``coach_id=None`` lists every author's notes for the session."""
        ...

    async def get_progress_note(self, session_id: str, note_id: str) -> ProgressNote | None: ...

    async def set_progress_note_visibility(
        self, session_id: str, note_id: str, visibility: NoteVisibility
    ) -> ProgressNote | None: ...


class CreateLessonPlanCommand(BaseModel):
    model_config = {"frozen": True}
    coach_id: str
    session_id: str
    title: str
    body: str


class CreateProgressNoteCommand(BaseModel):
    model_config = {"frozen": True}
    coach_id: str
    session_id: str
    student_id: str
    body: str
    visibility: NoteVisibility = "private"
    # True when the caller reaches the coach surface only as an assistant
    # coach; assistants may write notes but never share them.
    is_assistant: bool = False


class SetProgressNoteVisibilityCommand(BaseModel):
    model_config = {"frozen": True}
    coach_id: str
    session_id: str
    note_id: str
    visibility: NoteVisibility
    is_assistant: bool = False
    # Owner/admin covering the coach surface: may change any author's note.
    is_supervisor: bool = False


class CreateLessonPlan:
    def __init__(
        self,
        *,
        notes: CoachingNotesRepository,
        sessions: CoachSessionLookup,
    ) -> None:
        self._notes = notes
        self._sessions = sessions

    async def execute(self, cmd: CreateLessonPlanCommand) -> LessonPlan:
        if not await self._sessions.is_coach_assigned(cmd.coach_id, cmd.session_id):
            raise SessionNotAssigned("session not assigned", session_id=cmd.session_id)
        plan = LessonPlan(
            lesson_plan_id=str(new_ulid()),
            session_id=cmd.session_id,
            coach_id=cmd.coach_id,
            title=cmd.title,
            body=cmd.body,
            created_at=datetime.now(UTC),
        )
        await self._notes.add_lesson_plan(plan)
        return plan


class ListLessonPlans:
    def __init__(
        self,
        *,
        notes: CoachingNotesRepository,
        sessions: CoachSessionLookup,
    ) -> None:
        self._notes = notes
        self._sessions = sessions

    async def execute(self, coach_id: str, session_id: str) -> list[LessonPlan]:
        if not await self._sessions.is_coach_assigned(coach_id, session_id):
            raise SessionNotAssigned("session not assigned", session_id=session_id)
        return await self._notes.list_lesson_plans(session_id, coach_id)


class CreateProgressNote:
    def __init__(
        self,
        *,
        notes: CoachingNotesRepository,
        sessions: CoachSessionLookup,
        enrollments: ActiveEnrollmentLookup,
    ) -> None:
        self._notes = notes
        self._sessions = sessions
        self._enrollments = enrollments

    async def execute(self, cmd: CreateProgressNoteCommand) -> ProgressNote:
        if cmd.is_assistant and cmd.visibility == "shared":
            raise NoteShareForbidden(
                "assistant coaches cannot share notes with parents",
                session_id=cmd.session_id,
                student_id=cmd.student_id,
            )
        if not await self._sessions.is_coach_assigned(cmd.coach_id, cmd.session_id):
            raise SessionNotAssigned("session not assigned", session_id=cmd.session_id)
        if not await self._enrollments.is_active(cmd.session_id, cmd.student_id):
            raise StudentNotEnrolled("student not active in session", student_id=cmd.student_id)
        note = ProgressNote(
            note_id=str(new_ulid()),
            session_id=cmd.session_id,
            student_id=cmd.student_id,
            coach_id=cmd.coach_id,
            body=cmd.body,
            created_at=datetime.now(UTC),
            visibility=cmd.visibility,
        )
        await self._notes.add_progress_note(note)
        return note


class ListProgressNotes:
    def __init__(
        self,
        *,
        notes: CoachingNotesRepository,
        sessions: CoachSessionLookup,
    ) -> None:
        self._notes = notes
        self._sessions = sessions

    async def execute(
        self, coach_id: str, session_id: str, *, all_authors: bool = False
    ) -> list[ProgressNote]:
        """``all_authors=True`` (coach supervisors) returns every coach's notes
        for the session; coaches and assistants see only their own."""
        if not await self._sessions.is_coach_assigned(coach_id, session_id):
            raise SessionNotAssigned("session not assigned", session_id=session_id)
        return await self._notes.list_progress_notes(session_id, None if all_authors else coach_id)


class SetProgressNoteVisibility:
    def __init__(
        self,
        *,
        notes: CoachingNotesRepository,
        sessions: CoachSessionLookup,
    ) -> None:
        self._notes = notes
        self._sessions = sessions

    async def execute(self, cmd: SetProgressNoteVisibilityCommand) -> ProgressNote:
        if cmd.is_assistant:
            raise NoteShareForbidden(
                "assistant coaches cannot change note visibility",
                session_id=cmd.session_id,
                note_id=cmd.note_id,
            )
        if not await self._sessions.is_coach_assigned(cmd.coach_id, cmd.session_id):
            raise SessionNotAssigned("session not assigned", session_id=cmd.session_id)
        note = await self._notes.get_progress_note(cmd.session_id, cmd.note_id)
        if note is None or (not cmd.is_supervisor and note.coach_id != cmd.coach_id):
            raise NoteNotFound("note not found", session_id=cmd.session_id, note_id=cmd.note_id)
        updated = await self._notes.set_progress_note_visibility(
            cmd.session_id, cmd.note_id, cmd.visibility
        )
        if updated is None:
            raise NoteNotFound("note not found", session_id=cmd.session_id, note_id=cmd.note_id)
        return updated
