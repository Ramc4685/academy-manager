"""Mark attendance — Wave 1A core write.

Validates:
- Occurrence exists and belongs to the submitted recurring session.
- Occurrence is in the coach's assigned set for the occurrence date
  (``SessionNotAssigned``).
- Session is not cancelled (``SessionCancelled``).
- Student is currently enrolled (``StudentNotEnrolled``).
- No prior attendance with a different ``mutation_id`` for the same
  (occurrence, student) (``ConflictAttendanceExists``).

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
    OccurrenceLookup,
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
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id


class MarkAttendanceCommand(BaseModel):
    model_config = {"frozen": True}

    mutation_id: str  # client ULID
    occurrence_id: str
    session_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    marked_at_client: datetime | None = None
    client_app_version: str = Field(default="unknown")


class MarkAttendanceResult(BaseModel):
    model_config = {"frozen": True}

    attendance_id: str
    occurrence_id: str
    session_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    marked_at: datetime


class MarkAttendance:
    def __init__(
        self,
        *,
        attendance_repo: AttendanceRepository,
        occurrence_lookup: OccurrenceLookup,
        enrollment_lookup: EnrollmentLookup,
        outbox: Outbox,
        idempotency_store: IdempotencyStore,
        academy_id: str,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._attendance = attendance_repo
        self._occurrences = occurrence_lookup
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
        # 1. Occurrence + cancellation check.
        occurrence = await self._occurrences.get(cmd.occurrence_id)
        session_id_matches = occurrence is not None and (
            occurrence.session_id == cmd.session_id
            or occurrence.template_session_id == cmd.session_id
        )
        if not session_id_matches:
            raise SessionNotAssigned(
                "session occurrence not found or not assigned",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                coach_id=coach_id,
            )
        if occurrence.status == "cancelled":
            raise SessionCancelled(
                "session occurrence was cancelled",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
            )
        if coach_id not in {
            occurrence.scheduled_coach_id,
            occurrence.actual_coach_id,
            occurrence.substitute_coach_id,
        }:
            raise SessionNotAssigned(
                "session occurrence not assigned to this coach",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                coach_id=coach_id,
            )

        # 2. Student enrollment check.
        enrolled = await self._enrollments.is_active(cmd.session_id, cmd.student_id)
        if not enrolled and occurrence.template_session_id:
            enrolled = await self._enrollments.is_active(
                occurrence.template_session_id, cmd.student_id
            )
        if not enrolled:
            raise StudentNotEnrolled(
                "student not actively enrolled in session",
                session_id=cmd.session_id,
                student_id=cmd.student_id,
            )

        # 3. Conflict check — different mutation_id for same (occurrence, student).
        existing = await self._attendance.find_existing(cmd.occurrence_id, cmd.student_id)
        if existing and existing.attendance_id != cmd.mutation_id:
            raise ConflictAttendanceExists(
                "another mutation already recorded attendance",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                student_id=cmd.student_id,
                existing_attendance_id=existing.attendance_id,
            )

        # 4. Persist + outbox in the same logical transaction. The repo handles
        # tenant scope via TenantScopedRepository.
        now = self._now()
        academy_id = self._current_academy_id()
        attendance = Attendance(
            attendance_id=cmd.mutation_id,
            academy_id=academy_id,
            occurrence_id=cmd.occurrence_id,
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
                academy_id=academy_id,
                payload=AttendanceMarkedPayload(
                    attendance_id=attendance.attendance_id,
                    occurrence_id=attendance.occurrence_id,
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
            occurrence_id=attendance.occurrence_id,
            session_id=attendance.session_id,
            student_id=attendance.student_id,
            status=attendance.status,
            marked_at=attendance.marked_at,
        )

    def _current_academy_id(self) -> str:
        try:
            return current_academy_id()
        except TenantContextUnset:
            return self._academy_id
