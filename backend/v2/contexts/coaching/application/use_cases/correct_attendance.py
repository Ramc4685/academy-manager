"""Correct a previously recorded student attendance mark (#517).

Attendance is write-once at the mark endpoint (a second mutation 409s), so
mis-taps need an explicit correction path instead of loosening the conflict
rule:

- A **coach** assigned to the occurrence may correct within a grace window
  (48h from when the mark was recorded, the window the coach screen states).
  Outside the window ``CorrectionWindowExpired`` (403). A coach may not
  correct a mark an admin voided (``MarkVoided``, 403): un-voiding is admin
  work.
- An **admin** may correct at any time, and (S25) may give a first mark to
  a child the register missed, when the composition supplies
  ``student_known``: the student must be this academy's and the occurrence
  must exist in it, or the request is ``AttendanceNotFound`` (404).

Every correction keeps an audit trail on the row (``corrected_by`` /
``corrected_at`` / ``previous_status`` / ``correction_reason``) and emits
``Coaching.AttendanceCorrected`` to the outbox. Correcting to the same
status is a no-op (returns the current row, no write, no event), so retries
are safe.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from backend.v2.contexts.coaching.application.ports import (
    AttendanceRepository,
    OccurrenceLookup,
)
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import (
    ensure_occurrence_started,
)
from backend.v2.contexts.coaching.domain.errors import (
    AttendanceNotFound,
    CorrectionWindowExpired,
    MarkVoided,
    SessionCancelled,
    SessionNotAssigned,
)
from backend.v2.contexts.coaching.domain.events import (
    AttendanceCorrected,
    AttendanceCorrectedPayload,
    AttendanceMarked,
    AttendanceMarkedPayload,
)
from backend.v2.contexts.coaching.domain.models import Attendance
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid

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
    # A correction can follow a void (#554), so the status it replaced may be
    # "voided" even though nothing can be corrected *to* "voided".
    previous_status: Literal["present", "absent", "late", "voided"] | None
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
        student_known: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self._attendance = attendance_repo
        self._occurrences = occurrence_lookup
        self._outbox = outbox
        self._academy_id = academy_id
        self._now = clock
        self._coach_window = coach_window
        self._student_known = student_known

    async def execute(
        self,
        cmd: CorrectAttendanceCommand,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> CorrectAttendanceResult:
        existing = await self._attendance.find_existing(cmd.occurrence_id, cmd.student_id)
        now = self._now()
        if existing is None:
            if actor_role == "admin":
                return await self._first_mark(cmd, actor_id=actor_id, now=now)
            raise AttendanceNotFound(
                "no attendance mark exists for this occurrence and student",
                occurrence_id=cmd.occurrence_id,
                student_id=cmd.student_id,
            )

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
            if existing.status == "voided":
                raise MarkVoided(
                    "an admin voided this mark; ask an admin to correct it",
                    occurrence_id=cmd.occurrence_id,
                    student_id=cmd.student_id,
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

    async def _first_mark(
        self, cmd: CorrectAttendanceCommand, *, actor_id: str, now: datetime
    ) -> CorrectAttendanceResult:
        """An admin marks a child the register missed. Both reads are tenant-scoped."""
        not_found = AttendanceNotFound(
            "no attendance mark exists for this occurrence and student",
            occurrence_id=cmd.occurrence_id,
            student_id=cmd.student_id,
        )
        if self._student_known is None or not await self._student_known(cmd.student_id):
            raise not_found
        occurrence = await self._occurrences.get(cmd.occurrence_id)
        if occurrence is None:
            raise not_found
        # Same date guards as MarkAttendance: no marks on a cancelled (already
        # credited) date or on a date that has not started.
        if occurrence.status == "cancelled":
            raise SessionCancelled(
                "session occurrence was cancelled",
                session_id=occurrence.session_id,
                occurrence_id=cmd.occurrence_id,
            )
        ensure_occurrence_started(
            occurrence.starts_at,
            now,
            session_id=occurrence.session_id,
            occurrence_id=cmd.occurrence_id,
        )
        mark = Attendance(
            attendance_id=new_ulid(),
            academy_id=self._academy_id(),
            occurrence_id=cmd.occurrence_id,
            session_id=occurrence.session_id,
            student_id=cmd.student_id,
            marked_by=actor_id,
            marked_at=now,
            status=cmd.status,
            client_app_version="admin-correction",
        )
        await self._attendance.save(mark)
        # save() writes the mark only; the audit trail (who, when, why) rides on
        # the same update a correction uses, so the Inbox lists it like one.
        audited = mark.model_copy(
            update={"corrected_by": actor_id, "corrected_at": now, "correction_reason": cmd.reason}
        )
        await self._attendance.update_status(audited)
        await self._outbox.append(
            AttendanceMarked(
                aggregate_id=mark.attendance_id,
                academy_id=mark.academy_id,
                payload=AttendanceMarkedPayload(
                    attendance_id=mark.attendance_id,
                    occurrence_id=mark.occurrence_id,
                    session_id=mark.session_id,
                    student_id=mark.student_id,
                    marked_by=mark.marked_by,
                    marked_at=mark.marked_at,
                    status=mark.status,
                ),
            )
        )
        return self._result(audited)

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
