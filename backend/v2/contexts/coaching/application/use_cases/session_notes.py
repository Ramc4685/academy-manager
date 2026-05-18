"""Coach lesson plans and progress notes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel
from ulid import ULID

from backend.v2.contexts.coaching.domain.errors import SessionNotAssigned, StudentNotEnrolled


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


class CoachSessionLookup(Protocol):
    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool: ...


class ActiveEnrollmentLookup(Protocol):
    async def is_active(self, session_id: str, student_id: str) -> bool: ...


class CoachingNotesRepository(Protocol):
    async def add_lesson_plan(self, plan: LessonPlan) -> None: ...
    async def list_lesson_plans(self, session_id: str, coach_id: str) -> list[LessonPlan]: ...
    async def add_progress_note(self, note: ProgressNote) -> None: ...
    async def list_progress_notes(self, session_id: str, coach_id: str) -> list[ProgressNote]: ...


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
            lesson_plan_id=str(ULID()),
            session_id=cmd.session_id,
            coach_id=cmd.coach_id,
            title=cmd.title,
            body=cmd.body,
            created_at=datetime.now(timezone.utc),
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
        if not await self._sessions.is_coach_assigned(cmd.coach_id, cmd.session_id):
            raise SessionNotAssigned("session not assigned", session_id=cmd.session_id)
        if not await self._enrollments.is_active(cmd.session_id, cmd.student_id):
            raise StudentNotEnrolled("student not active in session", student_id=cmd.student_id)
        note = ProgressNote(
            note_id=str(ULID()),
            session_id=cmd.session_id,
            student_id=cmd.student_id,
            coach_id=cmd.coach_id,
            body=cmd.body,
            created_at=datetime.now(timezone.utc),
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

    async def execute(self, coach_id: str, session_id: str) -> list[ProgressNote]:
        if not await self._sessions.is_coach_assigned(coach_id, session_id):
            raise SessionNotAssigned("session not assigned", session_id=session_id)
        return await self._notes.list_progress_notes(session_id, coach_id)
