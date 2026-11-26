"""Wiring for the student-attendance correction/void surface (#517, #554).

Lives outside ``composition/admin.py`` because that module is at its
structural line budget (``tests/structural/test_composition_is_wiring.py``):
new wiring goes into a page-scoped module rather than pushing the budget up.

Three collaborators share one repository instance so a correction, a void and
the read-back all see the same tenant-scoped collection:

- ``correct`` flips a mark between the three real statuses (coach inside the
  48h window, admin any time).
- ``void`` annuls a mark, admin-only, reason required (#554).
- ``list_for_occurrence`` feeds the admin session-detail roster panel; each
  row carries ``student_name`` resolved inside the tenant (S25), "Former
  student" when the child's record is gone.
- ``review`` feeds the Admin Inbox "Attendance" tab: dates with no marks and
  recent corrections/voids.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.coaching.application.ports import OccurrenceLookup
from backend.v2.contexts.coaching.application.use_cases.attendance_review import (
    ListAttendanceReview,
)
from backend.v2.contexts.coaching.application.use_cases.correct_attendance import (
    CorrectAttendance,
)
from backend.v2.contexts.coaching.application.use_cases.void_attendance import (
    VoidAttendance,
)
from backend.v2.contexts.coaching.domain.models import Attendance
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_review_read_model import (
    MongoAttendanceReviewReadModel,
)
from backend.v2.shared.events import Outbox

#: Shown for a mark whose student no longer resolves in this academy.
FORMER_STUDENT = "Former student"


class NamedAttendance(Attendance):
    """An attendance row plus the child's name, for the admin class-date list."""

    student_name: str = FORMER_STUDENT


@dataclass(frozen=True)
class AttendanceCorrectionUseCases:
    correct: CorrectAttendance
    void: VoidAttendance
    list_for_occurrence: Callable[[str], object]
    review: ListAttendanceReview


def compose_attendance_corrections(
    db: AsyncIOMotorDatabase[Any],
    *,
    occurrence_lookup: OccurrenceLookup,
    outbox: Outbox,
    academy_id: Callable[[], str],
) -> AttendanceCorrectionUseCases:
    repo = MongoAttendanceRepository(db)
    review_reader = MongoAttendanceReviewReadModel(db)

    async def student_known(student_id: str) -> bool:
        return student_id in await review_reader.student_names([student_id])

    async def list_for_occurrence(occurrence_id: str) -> list[NamedAttendance]:
        rows = await repo.list_for_occurrence(occurrence_id)
        names = await review_reader.student_names([row.student_id for row in rows])
        return [
            NamedAttendance(
                **row.model_dump(), student_name=names.get(row.student_id, FORMER_STUDENT)
            )
            for row in rows
        ]

    return AttendanceCorrectionUseCases(
        correct=CorrectAttendance(
            attendance_repo=repo,
            occurrence_lookup=occurrence_lookup,
            outbox=outbox,
            academy_id=academy_id,
            student_known=student_known,
        ),
        # Void takes no occurrence lookup: an admin may void at any time, so
        # there is no assignment or grace-window check to make.
        void=VoidAttendance(attendance_repo=repo, outbox=outbox, academy_id=academy_id),
        list_for_occurrence=list_for_occurrence,
        review=ListAttendanceReview(reader=review_reader),
    )
