"""Coach roster write use cases — add/remove a student from an assigned session.

These are thin wrappers around the admin-level EditRosterAdd and the lower-level
enrollment writer, guarded by CoachAssignedSessionLookup so a coach can only
mutate rosters for sessions they are assigned to.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentWriter,
    SessionWriter,
    StudentWriter,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    EditRosterAdd,
    EditRosterAddCommand,
)
from backend.v2.contexts.enrollment.domain.errors import (
    EnrollmentNotFound,
    SessionNotAssigned,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment


class CoachSessionLookup(Protocol):
    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool: ...


class CoachAddStudentToRosterCommand(BaseModel):
    model_config = {"frozen": True}
    coach_id: str
    session_id: str
    student_id: str
    parent_id: str
    full_name: str


class CoachAddStudentToRoster:
    """Guard on assignment then delegate to EditRosterAdd."""

    def __init__(
        self,
        *,
        sessions: SessionWriter,
        enrollments: EnrollmentWriter,
        students: StudentWriter,
        assigned_sessions: CoachSessionLookup,
        academy_id: Callable[[], str],
    ) -> None:
        self._assigned_sessions = assigned_sessions
        self._sessions = sessions
        self._enrollments = enrollments
        self._students = students
        self._academy_id = academy_id

    async def execute(self, cmd: CoachAddStudentToRosterCommand) -> Enrollment:
        if not await self._assigned_sessions.is_coach_assigned(cmd.coach_id, cmd.session_id):
            raise SessionNotAssigned("session not assigned to coach", session_id=cmd.session_id)
        # EditRosterAdd resolves the provider at execute time, so the request
        # tenant wins over anything frozen at composition time.
        delegate = EditRosterAdd(
            sessions=self._sessions,
            enrollments=self._enrollments,
            students=self._students,
            academy_id=self._academy_id,
        )
        return await delegate.execute(
            EditRosterAddCommand(
                session_id=cmd.session_id,
                student_id=cmd.student_id,
                parent_id=cmd.parent_id,
                full_name=cmd.full_name,
                actor_id=cmd.coach_id,
                reason="coach_add",
            )
        )


class CoachRemoveStudentFromRosterCommand(BaseModel):
    model_config = {"frozen": True}
    coach_id: str
    session_id: str
    student_id: str


class CoachRemoveStudentFromRoster:
    """Guard on assignment then cancel the active enrollment for a student."""

    def __init__(
        self,
        *,
        enrollments: EnrollmentWriter,
        assigned_sessions: CoachSessionLookup,
    ) -> None:
        self._enrollments = enrollments
        self._assigned_sessions = assigned_sessions

    async def execute(self, cmd: CoachRemoveStudentFromRosterCommand) -> None:
        if not await self._assigned_sessions.is_coach_assigned(cmd.coach_id, cmd.session_id):
            raise SessionNotAssigned("session not assigned to coach", session_id=cmd.session_id)
        enrollment = await self._enrollments.find_for_session_student(
            cmd.session_id, cmd.student_id
        )
        if enrollment is None or enrollment.status != "active":
            raise EnrollmentNotFound(
                "active enrollment not found",
                session_id=cmd.session_id,
                student_id=cmd.student_id,
            )
        await self._enrollments.update_status(enrollment.enrollment_id, "cancelled")
