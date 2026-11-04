"""Void a recorded student attendance mark (#554).

A correction flips a mark between the three real statuses. A **void** says
the mark should never have existed: the row stays for its audit trail but
counts as *unmarked* everywhere downstream — attendance rate, payroll and
absence policy all enumerate the statuses they count and none of them list
``voided``.

Owner decision 2026-09-12:

- Only an **admin** may void, and may do so at any time (no grace window;
  there is deliberately no coach-facing void path — a coach's own mis-tap is
  a correction, inside the 24h window in ``correct_attendance``).
- A **reason is required**; it is stored on the row and carried on the event.

Voiding an already-voided mark is a no-op (no write, no event), so a retry
after a flaky response is safe. Un-voiding is an ordinary correction back to
a real status, which records ``previous_status="voided"``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

from backend.v2.contexts.coaching.application.ports import AttendanceRepository
from backend.v2.contexts.coaching.domain.errors import AttendanceNotFound
from backend.v2.contexts.coaching.domain.events import (
    AttendanceVoided,
    AttendanceVoidedPayload,
)
from backend.v2.contexts.coaching.domain.models import Attendance, AttendanceStatus
from backend.v2.shared.events import Outbox


class VoidAttendanceCommand(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    student_id: str
    # Required, and required to say something: a void erases a class record
    # from every report, so "why" is the only durable explanation anyone gets.
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("a reason is required to void an attendance mark")
        return cleaned


class VoidAttendanceResult(BaseModel):
    model_config = {"frozen": True}

    attendance_id: str
    occurrence_id: str
    session_id: str
    student_id: str
    status: AttendanceStatus
    previous_status: AttendanceStatus | None
    corrected_by: str | None
    corrected_at: datetime | None
    correction_reason: str | None


class VoidAttendance:
    def __init__(
        self,
        *,
        attendance_repo: AttendanceRepository,
        outbox: Outbox,
        academy_id: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._attendance = attendance_repo
        self._outbox = outbox
        self._academy_id = academy_id
        self._now = clock

    async def execute(self, cmd: VoidAttendanceCommand, *, actor_id: str) -> VoidAttendanceResult:
        existing = await self._attendance.find_existing(cmd.occurrence_id, cmd.student_id)
        if existing is None:
            raise AttendanceNotFound(
                "no attendance mark exists for this occurrence and student",
                occurrence_id=cmd.occurrence_id,
                student_id=cmd.student_id,
            )

        if existing.status == "voided":
            # Already annulled: keep the original void's audit trail intact.
            return self._result(existing)

        now = self._now()
        previous_status = existing.status
        voided = existing.model_copy(
            update={
                "status": "voided",
                "previous_status": previous_status,
                "corrected_by": actor_id,
                "corrected_at": now,
                "correction_reason": cmd.reason,
            }
        )
        await self._attendance.update_status(voided)
        await self._outbox.append(
            AttendanceVoided(
                aggregate_id=voided.attendance_id,
                academy_id=self._academy_id(),
                payload=AttendanceVoidedPayload(
                    attendance_id=voided.attendance_id,
                    occurrence_id=voided.occurrence_id,
                    session_id=voided.session_id,
                    student_id=voided.student_id,
                    previous_status=previous_status,
                    voided_by=actor_id,
                    voided_at=now,
                    reason=cmd.reason,
                ),
            )
        )
        return self._result(voided)

    @staticmethod
    def _result(attendance: Attendance) -> VoidAttendanceResult:
        return VoidAttendanceResult(
            attendance_id=attendance.attendance_id,
            occurrence_id=attendance.occurrence_id,
            session_id=attendance.session_id,
            student_id=attendance.student_id,
            status=attendance.status,
            previous_status=attendance.previous_status,
            corrected_by=attendance.corrected_by,
            corrected_at=attendance.corrected_at,
            correction_reason=attendance.correction_reason,
        )
