"""Coach roster write use cases — add/remove a student from an assigned session.

These are thin wrappers around the admin-level EditRosterAdd and the lower-level
enrollment writer, guarded by CoachAssignedSessionLookup so a coach can only
mutate rosters for sessions they are assigned to.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.ports import EnrollmentWriter
from backend.v2.contexts.enrollment.application.seat_broker import SeatBroker
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
    """Guard on assignment then delegate to EditRosterAdd.

    Issue #704 (second-review correction): this used to build a fresh
    ``EditRosterAdd`` on every ``execute()`` call, entirely outside
    ``composition/`` — the structural wiring test only scanned
    ``composition/*.py`` for constructions of brokerable seat-reservation
    classes, so this call site was both unbrokered in production AND
    invisible to the test meant to catch exactly that. A class full only
    because of held seats told a coach "session full" instead of reclaiming
    the longest hold, the same defect #704 already fixed for the admin
    roster-add path.

    ``EditRosterAdd`` already resolves ``academy_id`` at execute time when
    given a callable (see its constructor), so building ONE instance here at
    composition time — exactly how ``composition/admin.py`` wires the admin
    roster-add path — loses nothing: the request tenant still wins.
    """

    def __init__(
        self,
        *,
        edit_roster_add: EditRosterAdd,
        assigned_sessions: CoachSessionLookup,
    ) -> None:
        self._assigned_sessions = assigned_sessions
        self._delegate = edit_roster_add

    def set_seat_broker(self, seat_broker: SeatBroker) -> None:
        self._delegate.set_seat_broker(seat_broker)

    async def execute(self, cmd: CoachAddStudentToRosterCommand) -> Enrollment:
        if not await self._assigned_sessions.is_coach_assigned(cmd.coach_id, cmd.session_id):
            raise SessionNotAssigned("session not assigned to coach", session_id=cmd.session_id)
        return await self._delegate.execute(
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
        # Issue #699: renamed from "cancelled" — see domain/models.py
        # canonical_status().
        await self._enrollments.update_status(enrollment.enrollment_id, "deleted")
