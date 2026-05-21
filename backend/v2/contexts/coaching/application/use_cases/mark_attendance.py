"""Mark attendance — Wave 1A core write.

Validates:
- Session is in the coach's assigned set for the session's date
  (``SessionNotAssigned``).
- Session is not cancelled (``SessionCancelled``).
- Student is currently enrolled (``StudentNotEnrolled``).
- No prior attendance with a different ``mutation_id`` for the same
  (session, student) (``ConflictAttendanceExists``).

Idempotent on ``mutation_id`` via @idempotent so replays from offline-sync
return the original result.

Writes ``Coaching.AttendanceMarked`` to the outbox in the same transaction
as the attendance row. No cross-context writes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.coaching.application.ports import (
    AttendanceRepository,
    EnrollmentLookup,
    SessionLookup,
)
from backend.v2.contexts.coaching.domain.errors import (
    ConflictAttendanceExists,
    SessionCancelled,
    SessionNotAssigned,
    StudentNotEnrolled,
)
from backend.v2.contexts.coaching.domain.events import (
    AttendanceMarked,
    AttendanceMarkedPayload,
)
from backend.v2.contexts.coaching.domain.models import Attendance
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore, idempotent


class MarkAttendanceCommand(BaseModel):
    model_config = {"frozen": True}

    mutation_id: str  # client ULID
    session_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    marked_at_client: datetime | None = None
    client_app_version: str = Field(default="unknown")


class MarkAttendanceResult(BaseModel):
    model_config = {"frozen": True}

    attendance_id: str
    session_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    marked_at: datetime


class MarkAttendance:
    def __init__(
        self,
        *,
        attendance_repo: AttendanceRepository,
        session_lookup: SessionLookup,
        enrollment_lookup: EnrollmentLookup,
        outbox: Outbox,
        idempotency_store: IdempotencyStore,
        academy_id: str,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._attendance = attendance_repo
        self._sessions = session_lookup
        self._enrollments = enrollment_lookup
        self._outbox = outbox
        self._idempotency_store = idempotency_store
        self._academy_id = academy_id
        self._now = clock

    @idempotent(
        key_from=lambda self, cmd, coach_id: f"mark_attendance:{cmd.mutation_id}",
        result_type=MarkAttendanceResult,
    )
    async def execute(self, cmd: MarkAttendanceCommand, coach_id: str) -> MarkAttendanceResult:
        # 1. Session date + cancellation check.
        session_date = await self._sessions.session_date(cmd.session_id)
        if session_date is None:
            raise SessionNotAssigned(
                "session not found or not assigned",
                session_id=cmd.session_id,
                coach_id=coach_id,
            )
        if await self._sessions.is_cancelled(cmd.session_id):
            raise SessionCancelled("session was cancelled", session_id=cmd.session_id)
        if not await self._sessions.is_coach_assigned(coach_id, cmd.session_id, session_date):
            raise SessionNotAssigned(
                "session not assigned to this coach for that date",
                session_id=cmd.session_id,
                coach_id=coach_id,
            )

        # 2. Student enrollment check.
        if not await self._enrollments.is_active(cmd.session_id, cmd.student_id):
            raise StudentNotEnrolled(
                "student not actively enrolled in session",
                session_id=cmd.session_id,
                student_id=cmd.student_id,
            )

        # 3. Conflict check — different mutation_id for same (session, student).
        existing = await self._attendance.find_existing(cmd.session_id, cmd.student_id)
        if existing and existing.attendance_id != cmd.mutation_id:
            raise ConflictAttendanceExists(
                "another mutation already recorded attendance",
                session_id=cmd.session_id,
                student_id=cmd.student_id,
                existing_attendance_id=existing.attendance_id,
            )

        # 4. Persist + outbox in the same logical transaction. The repo handles
        # tenant scope via TenantScopedRepository.
        now = self._now()
        attendance = Attendance(
            attendance_id=cmd.mutation_id,
            academy_id=self._academy_id,
            session_id=cmd.session_id,
            student_id=cmd.student_id,
            marked_by=coach_id,
            marked_at=now,
            marked_at_client=cmd.marked_at_client,
            status=cmd.status,
            client_app_version=cmd.client_app_version,
        )
        await self._attendance.save(attendance)
        await self._outbox.append(
            AttendanceMarked(
                aggregate_id=attendance.attendance_id,
                academy_id=self._academy_id,
                payload=AttendanceMarkedPayload(
                    attendance_id=attendance.attendance_id,
                    session_id=attendance.session_id,
                    student_id=attendance.student_id,
                    marked_by=attendance.marked_by,
                    marked_at=attendance.marked_at,
                    status=attendance.status,
                ),
            )
        )

        return MarkAttendanceResult(
            attendance_id=attendance.attendance_id,
            session_id=attendance.session_id,
            student_id=attendance.student_id,
            status=attendance.status,
            marked_at=attendance.marked_at,
        )
