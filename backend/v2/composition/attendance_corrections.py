"""Wiring for the student-attendance correction/void surface (#517, #554).

Lives outside ``composition/admin.py`` because that module is at its
structural line budget (``tests/structural/test_composition_is_wiring.py``):
new wiring goes into a page-scoped module rather than pushing the budget up.

Three collaborators share one repository instance so a correction, a void and
the read-back all see the same tenant-scoped collection:

- ``correct`` flips a mark between the three real statuses (coach inside the
  24h window, admin any time).
- ``void`` annuls a mark, admin-only, reason required (#554).
- ``list_for_occurrence`` feeds the admin session-detail roster panel.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.coaching.application.ports import OccurrenceLookup
from backend.v2.contexts.coaching.application.use_cases.correct_attendance import (
    CorrectAttendance,
)
from backend.v2.contexts.coaching.application.use_cases.void_attendance import (
    VoidAttendance,
)
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.shared.events import Outbox


@dataclass(frozen=True)
class AttendanceCorrectionUseCases:
    correct: CorrectAttendance
    void: VoidAttendance
    list_for_occurrence: Callable[[str], object]


def compose_attendance_corrections(
    db: AsyncIOMotorDatabase[Any],
    *,
    occurrence_lookup: OccurrenceLookup,
    outbox: Outbox,
    academy_id: Callable[[], str],
) -> AttendanceCorrectionUseCases:
    repo = MongoAttendanceRepository(db)
    return AttendanceCorrectionUseCases(
        correct=CorrectAttendance(
            attendance_repo=repo,
            occurrence_lookup=occurrence_lookup,
            outbox=outbox,
            academy_id=academy_id,
        ),
        # Void takes no occurrence lookup: an admin may void at any time, so
        # there is no assignment or grace-window check to make.
        void=VoidAttendance(attendance_repo=repo, outbox=outbox, academy_id=academy_id),
        list_for_occurrence=repo.list_for_occurrence,
    )
