"""BulkMarkAttendance — mark attendance for multiple students in one batch.

Validates:
- Coach is assigned to the occurrence (SessionNotAssigned → 403 via route).
- All student_ids are enrolled in the session (fail-whole-batch on any miss).

Idempotent on ``mutation_id`` (batch-level): replays return the cached result.
Writes ``Coaching.AttendanceMarked`` to the outbox per entry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from backend.v2.contexts.coaching.application.ports import (
    AttendanceRepository,
    EnrollmentLookup,
    OccurrenceLookup,
)
from backend.v2.contexts.coaching.domain.errors import (
    BulkSessionNotAssigned,
    BulkStudentNotEnrolled,
    SessionCancelled,
)
from backend.v2.contexts.coaching.domain.events import (
    AttendanceMarked,
    AttendanceMarkedPayload,
)
from backend.v2.contexts.coaching.domain.models import Attendance
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore, idempotent


class BulkAttendanceEntry(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    status: Literal["present", "absent", "late"]


class BulkMarkAttendanceCommand(BaseModel):
    model_config = {"frozen": True}

    mutation_id: str  # idempotency key for the whole batch
    occurrence_id: str
    session_id: str
    entries: list[BulkAttendanceEntry]


class BulkAttendanceEntryResult(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    status: Literal["present", "absent", "late"]
    attendance_id: str


class BulkMarkAttendanceResult(BaseModel):
    model_config = {"frozen": True}

    results: list[BulkAttendanceEntryResult]


class BulkMarkAttendance:
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
        key_from=lambda self, cmd, coach_id: f"bulk_mark_attendance:{cmd.mutation_id}",
        result_type=BulkMarkAttendanceResult,
    )
    async def execute(
        self, cmd: BulkMarkAttendanceCommand, coach_id: str
    ) -> BulkMarkAttendanceResult:
        # 1. Validate occurrence exists and coach is assigned.
        occurrence = await self._occurrences.get(cmd.occurrence_id)
        session_id_matches = occurrence is not None and (
            occurrence.session_id == cmd.session_id
            or occurrence.template_session_id == cmd.session_id
        )
        if not session_id_matches:
            raise BulkSessionNotAssigned(
                "session occurrence not found or not assigned",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                coach_id=coach_id,
            )
        if coach_id not in {
            occurrence.scheduled_coach_id,
            occurrence.actual_coach_id,
            occurrence.substitute_coach_id,
        }:
            raise BulkSessionNotAssigned(
                "session occurrence not assigned to this coach",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                coach_id=coach_id,
            )

        # 1b. Reject cancelled occurrences before persisting anything.
        if occurrence.status == "cancelled":
            raise SessionCancelled(
                "occurrence is cancelled",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                coach_id=coach_id,
            )

        # 2. Validate all students are enrolled (fail whole batch on any miss).
        for entry in cmd.entries:
            enrolled = await self._enrollments.is_active(cmd.session_id, entry.student_id)
            if not enrolled and occurrence.template_session_id:
                enrolled = await self._enrollments.is_active(
                    occurrence.template_session_id, entry.student_id
                )
            if not enrolled:
                raise BulkStudentNotEnrolled(
                    "student not actively enrolled in session",
                    session_id=cmd.session_id,
                    student_id=entry.student_id,
                )

        # 3. Persist attendance and emit events per entry.
        now = self._now()
        entry_results: list[BulkAttendanceEntryResult] = []
        for i, entry in enumerate(cmd.entries):
            attendance_id = f"{cmd.mutation_id}:{i}"
            attendance = Attendance(
                attendance_id=attendance_id,
                academy_id=self._academy_id,
                occurrence_id=cmd.occurrence_id,
                session_id=cmd.session_id,
                student_id=entry.student_id,
                marked_by=coach_id,
                marked_at=now,
                marked_at_client=None,
                status=entry.status,
                client_app_version="bulk",
            )
            await self._attendance.save(attendance)
            await self._outbox.append(
                AttendanceMarked(
                    aggregate_id=attendance.attendance_id,
                    academy_id=self._academy_id,
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
            entry_results.append(
                BulkAttendanceEntryResult(
                    student_id=entry.student_id,
                    status=entry.status,
                    attendance_id=attendance_id,
                )
            )

        return BulkMarkAttendanceResult(results=entry_results)
