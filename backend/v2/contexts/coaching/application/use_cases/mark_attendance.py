"""Mark attendance — Wave 1A core write.

Validates:
- Occurrence exists and belongs to the submitted recurring session.
- Occurrence is in the coach's assigned set for the occurrence date
  (``SessionNotAssigned``).
- Session is not cancelled (``SessionCancelled``).
- Occurrence starts no later than ``MARK_LEAD_TIME`` from now
  (``OccurrenceNotStarted``): a future class cannot be marked.
- Student is eligible for this occurrence: actively enrolled, or holding an
  approved make-up / trial roster entry for it (``StudentNotEnrolled``).
- No prior attendance with a different ``mutation_id`` for the same
  (occurrence, student) (``ConflictAttendanceExists``).

Idempotent on ``mutation_id`` via @idempotent so replays from offline-sync
return the original result. A replay whose idempotency record was never
stored (the put failed after the row committed, or two replays raced) finds
its own row (``attendance_id == mutation_id``) and returns it as success
instead of a 409.

Writes ``Coaching.AttendanceMarked`` to the outbox in the same transaction
as the attendance row. No cross-context writes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.coaching.application.ports import (
    AttendanceRepository,
    EnrollmentLookup,
    OccurrenceDetails,
    OccurrenceLookup,
)
from backend.v2.contexts.coaching.domain.errors import (
    ConflictAttendanceExists,
    OccurrenceNotStarted,
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

# How early a coach may mark before the class starts (arrivals before the
# start time). Anything later in the future is refused.
MARK_LEAD_TIME = timedelta(minutes=60)


def ensure_occurrence_started(starts_at: datetime, now: datetime, **details: object) -> None:
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=UTC)
    if starts_at - now > MARK_LEAD_TIME:
        raise OccurrenceNotStarted(
            "this class has not started yet; mark it once it begins",
            starts_at=starts_at.isoformat(),
            **details,
        )


def is_assigned_to_occurrence(occurrence: OccurrenceDetails, coach_id: str) -> bool:
    """Scheduled, actual, substitute or assistant coach of this occurrence.

    Assistant coaches mark attendance like an assigned coach (they are never
    paid for it; payroll ignores the list).
    """
    return coach_id in {
        occurrence.scheduled_coach_id,
        occurrence.actual_coach_id,
        occurrence.substitute_coach_id,
        *occurrence.assistant_coach_ids,
    }


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
        academy_id: Callable[[], str],
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
        # Server-derived scope prefix (tenant + coach): a client-supplied
        # mutation_id can never collide with — or pre-claim / read back — a key
        # cached for another academy or another coach (#544).
        key_from=lambda self, cmd, coach_id, supervisor=False: (
            f"mark_attendance:{self._academy_id()}:{coach_id}:{cmd.mutation_id}"
        ),
        result_type=MarkAttendanceResult,
    )
    async def execute(
        self,
        cmd: MarkAttendanceCommand,
        coach_id: str,
        *,
        supervisor: bool = False,
    ) -> MarkAttendanceResult:
        """Record one mark.

        ``supervisor=True`` (an academy admin/owner covering the session)
        skips only the "coach is assigned to this occurrence" check. The
        occurrence, cancellation, enrollment and conflict checks still apply,
        and the mark is attributed to ``coach_id`` — the supervisor's own id.
        """
        # 1. Occurrence + cancellation check.
        occurrence = await self._occurrences.get(cmd.occurrence_id)
        if occurrence is None or (
            occurrence.session_id != cmd.session_id
            and occurrence.template_session_id != cmd.session_id
        ):
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
        if not supervisor and not is_assigned_to_occurrence(occurrence, coach_id):
            raise SessionNotAssigned(
                "session occurrence not assigned to this coach",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                coach_id=coach_id,
            )
        ensure_occurrence_started(
            occurrence.starts_at,
            self._now(),
            session_id=cmd.session_id,
            occurrence_id=cmd.occurrence_id,
        )

        # 2. Student eligibility: an active enrollment in the session (or its
        # recurring template) OR an approved one-time make-up / trial roster
        # entry for exactly this occurrence (issue #672). Paused, cancelled
        # and withdrawn enrollments remain ineligible.
        eligibility = await self._enrollments.attendance_eligibility(
            occurrence_id=cmd.occurrence_id,
            session_id=cmd.session_id,
            template_session_id=occurrence.template_session_id,
            student_id=cmd.student_id,
        )
        if eligibility is None:
            raise StudentNotEnrolled(
                "student not actively enrolled in session and not on the occurrence roster",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                student_id=cmd.student_id,
            )

        # 3. Conflict check — different mutation_id for same (occurrence, student).
        existing = await self._attendance.find_existing(cmd.occurrence_id, cmd.student_id)
        if existing and existing.attendance_id == cmd.mutation_id and existing.status != "voided":
            return self._result(existing)
        if existing:
            raise ConflictAttendanceExists(
                "another mutation already recorded attendance",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                student_id=cmd.student_id,
                existing_attendance_id=existing.attendance_id,
                existing_status=existing.status,
            )

        # 4. Persist + outbox in the same logical transaction. The repo handles
        # tenant scope via TenantScopedRepository.
        now = self._now()
        # Request-time tenant via the injected provider — never a boot-time value.
        academy_id = self._academy_id()
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
            entry_source=eligibility.source,
        )
        try:
            await self._attendance.save(attendance)
        except ConflictAttendanceExists as exc:
            # A concurrent replay of this same mutation won the insert.
            if exc.details.get("existing_attendance_id") != cmd.mutation_id:
                raise
            return self._result(attendance)
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
                    entry_source=attendance.entry_source,
                ),
            )
        )

        return self._result(attendance)

    @staticmethod
    def _result(attendance: Attendance) -> MarkAttendanceResult:
        return MarkAttendanceResult(
            attendance_id=attendance.attendance_id,
            occurrence_id=attendance.occurrence_id,
            session_id=attendance.session_id,
            student_id=attendance.student_id,
            status=attendance.status,
            marked_at=attendance.marked_at,
        )
