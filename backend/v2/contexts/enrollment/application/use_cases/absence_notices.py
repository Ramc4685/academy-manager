"""Parent-submitted absence notices (R1).

Parents notify the academy ahead of a scheduled occurrence that their child
will be absent. Submission is allowed any time before the occurrence starts;
``notice_window_met`` only flags whether the parent gave the academy's
configured minimum notice — it does not block submission. Task 4 (makeup
eligibility) reads this flag.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.domain.errors import StudentNotFound
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence, Student
from backend.v2.contexts.enrollment.domain.self_service import (
    AbsenceWindowClosed,
    DuplicateAbsenceNotice,
    ParentSelfServicePolicy,
)
from backend.v2.shared.ids import new_ulid


class AbsenceNotice(BaseModel):
    model_config = {"frozen": True}

    notice_id: str
    academy_id: str
    student_id: str
    occurrence_id: str
    session_id: str
    submitted_by: str  # parent user_id
    submitted_at: datetime
    notice_window_met: bool


class SubmitAbsenceNoticeCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    student_id: str
    occurrence_id: str


class StudentQuery(Protocol):
    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None: ...


class SessionOccurrenceRepository(Protocol):
    async def get(self, occurrence_id: str) -> SessionOccurrence | None: ...


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


class SubmitAbsenceNotice:
    def __init__(
        self,
        *,
        students: StudentQuery,
        occurrences: SessionOccurrenceRepository,
        notices: AbsenceNoticeRepository,
        policies: SelfServicePolicyRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._students = students
        self._occurrences = occurrences
        self._notices = notices
        self._policies = policies
        self._now = clock

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
        return notice


class ListParentAbsences:
    def __init__(self, *, notices: AbsenceNoticeRepository) -> None:
        self._notices = notices

    async def execute(self, parent_id: str) -> list[AbsenceNotice]:
        return await self._notices.list_for_parent(parent_id)
