"""Parent-submitted absence notices (R1).

Parents notify the academy ahead of a scheduled occurrence that their child
will be absent. Submission is allowed any time before the occurrence starts;
``notice_window_met`` only flags whether the parent gave the academy's
configured minimum notice — it does not block submission. Task 4 (makeup
eligibility) reads this flag.

Once a notice is persisted the optional ``AbsenceNoticeNotifier`` is told
(#616): the adapter in ``composition/absence_notifications.py`` alerts the
staff and confirms to the parent. It is best-effort — the write wins, and a
notifier failure is logged and swallowed, never surfaced to the caller.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.domain.errors import OccurrenceNotFound, StudentNotFound
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence, Student
from backend.v2.contexts.enrollment.domain.self_service import (
    AbsenceWindowClosed,
    DuplicateAbsenceNotice,
    ParentSelfServicePolicy,
    StudentNotEnrolledInSession,
)
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)


class AbsenceNotice(BaseModel):
    model_config = {"frozen": True}

    notice_id: str
    academy_id: str
    student_id: str
    occurrence_id: str
    session_id: str
    submitted_by: str  # parent user_id, or the admin user_id when recorded_by_admin
    submitted_at: datetime
    notice_window_met: bool
    # True when an admin recorded the notice on the parent's behalf (#616);
    # parent submissions leave the default.
    recorded_by_admin: bool = False


class SubmitAbsenceNoticeCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    student_id: str
    occurrence_id: str


class RecordAbsenceNoticeForStudentCommand(BaseModel):
    model_config = {"frozen": True}

    actor_id: str  # admin/owner user_id
    student_id: str
    occurrence_id: str
    counts_toward_makeup: bool = True


class StudentQuery(Protocol):
    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None: ...


class StudentLookup(Protocol):
    """Tenant-scoped student lookup for the admin path (no parent check)."""

    async def by_ids(self, student_ids: list[str]) -> list[Student]: ...


class SessionOccurrenceRepository(Protocol):
    async def get(self, occurrence_id: str) -> SessionOccurrence | None: ...


class EnrollmentQuery(Protocol):
    async def is_active_or_paused(self, session_id: str, student_id: str) -> bool: ...


class SelfServicePolicyRepository(Protocol):
    async def get_or_default(self) -> ParentSelfServicePolicy: ...


class AbsenceNoticeRepository(Protocol):
    async def add(self, notice: AbsenceNotice) -> None: ...

    async def get_for_occurrence_and_student(
        self, occurrence_id: str, student_id: str
    ) -> AbsenceNotice | None: ...

    async def list_for_parent(self, parent_id: str) -> list[AbsenceNotice]: ...

    async def list_for_occurrence(self, occurrence_id: str) -> list[AbsenceNotice]: ...

    async def list_for_student(self, student_id: str) -> list[AbsenceNotice]: ...


class AbsenceNoticeNotifier(Protocol):
    """Tell the people who need to know that an absence notice was filed (#616).

    Same shape as ``DeclinePauseRequest``'s ``PauseRequestDeclinedNotifier``:
    a one-method Protocol here, the adapter that resolves recipients and
    sends in ``composition/absence_notifications.py`` (enrollment may never
    import communications). Implementations are best-effort and MUST NOT be
    allowed to fail the write — both use cases wrap the call in
    catch/log/continue. The adapter decides who hears about it from the
    notice itself: staff always, the parent only when they filed it
    (``recorded_by_admin`` is False).
    """

    async def absence_notice_submitted(
        self, *, notice: AbsenceNotice, occurrence: SessionOccurrence, student: Student
    ) -> None: ...


async def _notify_submitted(
    notifier: AbsenceNoticeNotifier | None,
    *,
    notice: AbsenceNotice,
    occurrence: SessionOccurrence,
    student: Student,
) -> None:
    """The write already happened; nothing the notifier does may undo it."""
    if notifier is None:
        return
    try:
        await notifier.absence_notice_submitted(
            notice=notice, occurrence=occurrence, student=student
        )
    except Exception:
        log.exception(
            "absence_notice_notify_failed",
            extra={"notice_id": notice.notice_id, "occurrence_id": notice.occurrence_id},
        )


class SubmitAbsenceNotice:
    def __init__(
        self,
        *,
        students: StudentQuery,
        occurrences: SessionOccurrenceRepository,
        enrollments: EnrollmentQuery,
        notices: AbsenceNoticeRepository,
        policies: SelfServicePolicyRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        notifier: AbsenceNoticeNotifier | None = None,
    ) -> None:
        self._students = students
        self._occurrences = occurrences
        self._enrollments = enrollments
        self._notices = notices
        self._policies = policies
        self._now = clock
        self._notifier = notifier

    async def execute(self, cmd: SubmitAbsenceNoticeCommand) -> AbsenceNotice:
        student = await self._students.get_for_parent(cmd.parent_id, cmd.student_id)
        if student is None:
            raise StudentNotFound("student not found for parent", student_id=cmd.student_id)

        occurrence = await self._occurrences.get(cmd.occurrence_id)
        now = self._now()
        if occurrence is None or occurrence.status != "scheduled" or occurrence.start_at <= now:
            raise AbsenceWindowClosed(
                "occurrence has already started or is not open for notice",
                occurrence_id=cmd.occurrence_id,
            )

        if not await self._enrollments.is_active_or_paused(occurrence.session_id, cmd.student_id):
            raise StudentNotEnrolledInSession(
                "student has no active or paused enrollment in this occurrence's session",
                session_id=occurrence.session_id,
                student_id=cmd.student_id,
            )

        existing = await self._notices.get_for_occurrence_and_student(
            cmd.occurrence_id, cmd.student_id
        )
        if existing is not None:
            raise DuplicateAbsenceNotice(
                "absence notice already submitted for this occurrence",
                occurrence_id=cmd.occurrence_id,
                student_id=cmd.student_id,
            )

        policy = await self._policies.get_or_default()
        notice_window_met = (occurrence.start_at - now) >= timedelta(
            hours=policy.absence_notice_min_hours
        )

        notice = AbsenceNotice(
            notice_id=str(new_ulid()),
            academy_id=occurrence.academy_id,
            student_id=cmd.student_id,
            occurrence_id=cmd.occurrence_id,
            session_id=occurrence.session_id,
            submitted_by=cmd.parent_id,
            submitted_at=now,
            notice_window_met=notice_window_met,
        )
        await self._notices.add(notice)
        await _notify_submitted(
            self._notifier, notice=notice, occurrence=occurrence, student=student
        )
        return notice


class RecordAbsenceNoticeForStudent:
    """An admin records an absence notice on a parent's behalf (#616).

    Same guards as ``SubmitAbsenceNotice`` minus the ones that only make sense
    for a parent: there is no parent ownership check (the student only has to
    exist in the tenant), and the occurrence may already have started or be
    over — the whole point is capturing a phone call or a note handed to the
    coach after the fact. ``notice_window_met`` is whatever the admin decides
    (``counts_toward_makeup``) rather than computed from the policy clock, so
    the make-up eligibility path (Task 4) treats it like an on-time parent
    notice when the admin says it should. The notifier (when wired) alerts
    the staff but sends the parent nothing — the notice carries
    ``recorded_by_admin=True`` and the adapter reads that.
    """

    def __init__(
        self,
        *,
        students: StudentLookup,
        occurrences: SessionOccurrenceRepository,
        enrollments: EnrollmentQuery,
        notices: AbsenceNoticeRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        notifier: AbsenceNoticeNotifier | None = None,
    ) -> None:
        self._students = students
        self._occurrences = occurrences
        self._enrollments = enrollments
        self._notices = notices
        self._now = clock
        self._notifier = notifier

    async def execute(self, cmd: RecordAbsenceNoticeForStudentCommand) -> AbsenceNotice:
        students = await self._students.by_ids([cmd.student_id])
        student = next((s for s in students if s.student_id == cmd.student_id), None)
        if student is None:
            raise StudentNotFound("student not found", student_id=cmd.student_id)

        occurrence = await self._occurrences.get(cmd.occurrence_id)
        if occurrence is None:
            raise OccurrenceNotFound("no such class date", occurrence_id=cmd.occurrence_id)

        if not await self._enrollments.is_active_or_paused(occurrence.session_id, cmd.student_id):
            raise StudentNotEnrolledInSession(
                "student has no active or paused enrollment in this occurrence's session",
                session_id=occurrence.session_id,
                student_id=cmd.student_id,
            )

        existing = await self._notices.get_for_occurrence_and_student(
            cmd.occurrence_id, cmd.student_id
        )
        if existing is not None:
            raise DuplicateAbsenceNotice(
                "absence notice already submitted for this occurrence",
                occurrence_id=cmd.occurrence_id,
                student_id=cmd.student_id,
            )

        notice = AbsenceNotice(
            notice_id=str(new_ulid()),
            academy_id=occurrence.academy_id,
            student_id=cmd.student_id,
            occurrence_id=cmd.occurrence_id,
            session_id=occurrence.session_id,
            submitted_by=cmd.actor_id,
            submitted_at=self._now(),
            notice_window_met=cmd.counts_toward_makeup,
            recorded_by_admin=True,
        )
        await self._notices.add(notice)
        await _notify_submitted(
            self._notifier, notice=notice, occurrence=occurrence, student=student
        )
        return notice


class ListParentAbsences:
    def __init__(self, *, notices: AbsenceNoticeRepository) -> None:
        self._notices = notices

    async def execute(self, parent_id: str) -> list[AbsenceNotice]:
        return await self._notices.list_for_parent(parent_id)
