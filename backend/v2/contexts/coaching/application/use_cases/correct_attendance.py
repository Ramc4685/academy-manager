"""Correct a previously recorded student attendance mark (#517).

Attendance is write-once at the mark endpoint (a second mutation 409s), so
mis-taps need an explicit correction path instead of loosening the conflict
rule:

- A **coach** assigned to the occurrence may correct within a grace window
  (48h from when the mark was recorded). Outside the window
  ``CorrectionWindowExpired`` (403).
- An **admin** may correct at any time.

Every correction keeps an audit trail on the row (``corrected_by`` /
``corrected_at`` / ``previous_status`` / ``correction_reason``) and emits
``Coaching.AttendanceCorrected`` to the outbox. Correcting to the same
status is a no-op (returns the current row, no write, no event), so retries
are safe.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from backend.v2.contexts.coaching.application.ports import (
    AttendanceRepository,
    OccurrenceLookup,
)
from backend.v2.contexts.coaching.domain.errors import (
    AttendanceNotFound,
    CorrectionWindowExpired,
    SessionNotAssigned,
)
from backend.v2.contexts.coaching.domain.events import (
    AttendanceCorrected,
    AttendanceCorrectedPayload,
)
from backend.v2.contexts.coaching.domain.models import Attendance
from backend.v2.shared.events import Outbox

COACH_CORRECTION_WINDOW = timedelta(hours=48)

ActorRole = Literal["coach", "admin"]


class CorrectAttendanceCommand(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    reason: str | None = None


class CorrectAttendanceResult(BaseModel):
    model_config = {"frozen": True}

    attendance_id: str
    occurrence_id: str
    session_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    previous_status: Literal["present", "absent", "late"] | None
    corrected_by: str | None
    corrected_at: datetime | None


class CorrectAttendance:
    def __init__(
        self,
        *,
        attendance_repo: AttendanceRepository,
        occurrence_lookup: OccurrenceLookup,
        outbox: Outbox,
        academy_id: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        coach_window: timedelta = COACH_CORRECTION_WINDOW,
    ) -> None:
        self._attendance = attendance_repo
        self._occurrences = occurrence_lookup
        self._outbox = outbox
        self._academy_id = academy_id
        self._now = clock
        self._coach_window = coach_window

    async def execute(
        self,
        cmd: CorrectAttendanceCommand,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> CorrectAttendanceResult:
        existing = await self._attendance.find_existing(cmd.occurrence_id, cmd.student_id)
        if existing is None:
            raise AttendanceNotFound(
                "no attendance mark exists for this occurrence and student",
                occurrence_id=cmd.occurrence_id,
                student_id=cmd.student_id,
            )

        now = self._now()

        if actor_role == "coach":
            occurrence = await self._occurrences.get(cmd.occurrence_id)
            if occurrence is None or actor_id not in {
                occurrence.scheduled_coach_id,
                occurrence.actual_coach_id,
                occurrence.substitute_coach_id,
                *occurrence.assistant_coach_ids,
            }:
                raise SessionNotAssigned(
                    "session occurrence not found or not assigned to this coach",
                    occurrence_id=cmd.occurrence_id,
                    coach_id=actor_id,
                )
            marked_at = existing.marked_at
            if marked_at.tzinfo is None:
                marked_at = marked_at.replace(tzinfo=UTC)
            if now - marked_at > self._coach_window:
                raise CorrectionWindowExpired(
                    "coach correction window has expired; ask an admin to correct",
                    occurrence_id=cmd.occurrence_id,
                    student_id=cmd.student_id,
                    marked_at=marked_at.isoformat(),
                )

        if cmd.status == existing.status:
            # No-op: nothing to change, no audit entry, no event.
            return self._result(existing)

        corrected = existing.model_copy(
            update={
                "status": cmd.status,
                "previous_status": existing.status,
                "corrected_by": actor_id,
                "corrected_at": now,
                "correction_reason": cmd.reason,
            }
        )
        await self._attendance.update_status(corrected)
        await self._outbox.append(
            AttendanceCorrected(
                aggregate_id=corrected.attendance_id,
                academy_id=self._academy_id(),
                payload=AttendanceCorrectedPayload(
                    attendance_id=corrected.attendance_id,
                    occurrence_id=corrected.occurrence_id,
                    session_id=corrected.session_id,
                    student_id=corrected.student_id,
                    previous_status=existing.status,
                    status=corrected.status,
                    corrected_by=actor_id,
                    corrected_at=now,
                    actor_role=actor_role,
                    reason=cmd.reason,
                ),
            )
        )
        return self._result(corrected)

    @staticmethod
    def _result(attendance: Attendance) -> CorrectAttendanceResult:
        return CorrectAttendanceResult(
            attendance_id=attendance.attendance_id,
            occurrence_id=attendance.occurrence_id,
            session_id=attendance.session_id,
            student_id=attendance.student_id,
            status=attendance.status,
            previous_status=attendance.previous_status,
            corrected_by=attendance.corrected_by,
            corrected_at=attendance.corrected_at,
        )
