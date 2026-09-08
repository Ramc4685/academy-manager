"""BulkMarkAttendance — mark attendance for multiple students in one batch.

Validates:
- Coach is assigned to the occurrence (SessionNotAssigned → 403 via route).
- All student_ids are eligible for the occurrence — actively enrolled or
  holding an approved make-up / trial roster entry (fail-whole-batch on any
  miss; ``BulkStudentNotEnrolled.details["student_ids"]`` names them).

Idempotent on ``mutation_id`` (batch-level): replays return the cached result.
Writes ``Coaching.AttendanceMarked`` to the outbox per entry.
"""

from __future__ import annotations

from collections.abc import Callable
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
    ConflictAttendanceExists,
    SessionCancelled,
)
from backend.v2.contexts.coaching.domain.events import (
    AttendanceMarked,
    AttendanceMarkedPayload,
)
from backend.v2.contexts.coaching.domain.models import Attendance, AttendanceEntrySource
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
            f"bulk_mark_attendance:{self._academy_id()}:{coach_id}:{cmd.mutation_id}"
        ),
        result_type=BulkMarkAttendanceResult,
    )
    async def execute(
        self,
        cmd: BulkMarkAttendanceCommand,
        coach_id: str,
        *,
        supervisor: bool = False,
    ) -> BulkMarkAttendanceResult:
        # 1. Validate occurrence exists and coach is assigned. A supervisor
        # (academy admin/owner covering the session) skips only the
        # assignment membership test; see MarkAttendance.execute.
        occurrence = await self._occurrences.get(cmd.occurrence_id)
        if occurrence is None or (
            occurrence.session_id != cmd.session_id
            and occurrence.template_session_id != cmd.session_id
        ):
            raise BulkSessionNotAssigned(
                "session occurrence not found or not assigned",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                coach_id=coach_id,
            )
        if not supervisor and coach_id not in {
            occurrence.scheduled_coach_id,
            occurrence.actual_coach_id,
            occurrence.substitute_coach_id,
            *occurrence.assistant_coach_ids,
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

        # 2. Validate every student is eligible for this occurrence — an
        # active enrollment, or an approved make-up / trial roster entry
        # (issue #672). The whole batch fails on any miss, and the error
        # names every ineligible student so the coach can act on it.
        sources: dict[str, AttendanceEntrySource] = {}
        ineligible: list[str] = []
        for entry in cmd.entries:
            if entry.student_id in sources or entry.student_id in ineligible:
                continue
            eligibility = await self._enrollments.attendance_eligibility(
                occurrence_id=cmd.occurrence_id,
                session_id=cmd.session_id,
                template_session_id=occurrence.template_session_id,
                student_id=entry.student_id,
            )
            if eligibility is None:
                ineligible.append(entry.student_id)
            else:
                sources[entry.student_id] = eligibility.source
        if ineligible:
            raise BulkStudentNotEnrolled(
                "students not actively enrolled in session and not on the occurrence roster",
                session_id=cmd.session_id,
                occurrence_id=cmd.occurrence_id,
                student_ids=ineligible,
            )

        # 2b. Reject duplicate student_ids within the batch.
        if len({e.student_id for e in cmd.entries}) != len(cmd.entries):
            raise BulkStudentNotEnrolled(
                "duplicate student_id entries in batch", session_id=cmd.session_id
            )

        # 2c. Pre-flight: check for existing attendance before writing any rows so
        # a conflict never causes a partial batch (raises before first write).
        for entry in cmd.entries:
            existing = await self._attendance.find_existing(cmd.occurrence_id, entry.student_id)
            if existing is not None:
                raise ConflictAttendanceExists(
                    "attendance already recorded for this occurrence and student",
                    session_id=cmd.session_id,
                    occurrence_id=cmd.occurrence_id,
                    student_id=entry.student_id,
                    existing_attendance_id=existing.attendance_id,
                )

        # 3. Persist attendance and emit events per entry.
        now = self._now()
        # Request-time tenant via the injected provider — never a boot-time value.
        academy_id = self._academy_id()
        entry_results: list[BulkAttendanceEntryResult] = []
        for i, entry in enumerate(cmd.entries):
            attendance_id = f"{cmd.mutation_id}:{i}"
            attendance = Attendance(
                attendance_id=attendance_id,
                academy_id=academy_id,
                occurrence_id=cmd.occurrence_id,
                session_id=cmd.session_id,
                student_id=entry.student_id,
                marked_by=coach_id,
                marked_at=now,
                marked_at_client=None,
                status=entry.status,
                client_app_version="bulk",
                entry_source=sources[entry.student_id],
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
                        entry_source=attendance.entry_source,
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
