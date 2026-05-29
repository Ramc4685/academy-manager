"""Mark coach payroll attendance for one occurrence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.coaching.application.ports import (
    CoachAttendanceRepository,
    OccurrenceLookup,
)
from backend.v2.contexts.coaching.domain.models import (
    CoachAttendance,
    CoachAttendanceRole,
    CoachAttendanceSource,
    CoachAttendanceStatus,
)
from backend.v2.shared.ids import new_ulid


class MarkCoachAttendanceCommand(BaseModel):
    occurrence_id: str
    coach_id: str
    status: CoachAttendanceStatus
    role: CoachAttendanceRole = "lead"
    source: CoachAttendanceSource
    rate_override_minor: int | None = Field(default=None, ge=0)
    note: str = ""


class MarkCoachAttendance:
    def __init__(
        self,
        *,
        coach_attendance: CoachAttendanceRepository,
        occurrence_lookup: OccurrenceLookup,
        academy_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._coach_attendance = coach_attendance
        self._occurrence_lookup = occurrence_lookup
        self._academy_id = academy_id
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        command: MarkCoachAttendanceCommand,
        *,
        actor_id: str,
    ) -> CoachAttendance:
        occurrence = await self._occurrence_lookup.get(command.occurrence_id)
        if occurrence is None:
            raise ValueError("Occurrence not found")

        if command.source == "coach_self":
            assigned = {
                occurrence.scheduled_coach_id,
                occurrence.actual_coach_id,
                occurrence.substitute_coach_id,
            }
            if command.coach_id != actor_id or command.coach_id not in assigned:
                raise PermissionError("Coach is not assigned to this occurrence")

        existing = await self._coach_attendance.find_for_occurrence_coach(
            command.occurrence_id,
            command.coach_id,
        )
        row = CoachAttendance(
            attendance_id=existing.attendance_id if existing else new_ulid(),
            academy_id=self._academy_id,
            occurrence_id=command.occurrence_id,
            coach_id=command.coach_id,
            status=command.status,
            role=command.role,
            source=command.source,
            marked_by=actor_id,
            marked_at=self._clock(),
            rate_override_minor=command.rate_override_minor,
            note=command.note,
        )
        return await self._coach_attendance.upsert(row)
