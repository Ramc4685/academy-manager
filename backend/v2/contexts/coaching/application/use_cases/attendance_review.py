"""Attendance work that needs an admin's eyes (Admin Inbox "Attendance" tab).

Two kinds of item:

- **Missing attendance**: a class date that happened, was not cancelled, had
  students on the roster, and has no recorded mark at all. A coach gets the
  same 48h window the coach Today screen uses for "Recent, not fully marked"
  (and the coach correction window), so a date only reaches the admin once the
  coach's own reminder has stopped showing it. Dates older than the lookback
  drop off: a register nobody took a month ago is history, not a task.
- **Corrections**: marks changed or voided after they were first recorded,
  for review. Informational, like absence notices: they carry no badge.

The reader is tenant-scoped (request academy); nothing here sees academy_id.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from backend.v2.contexts.coaching.application.ports import (
    AttendanceReviewReader,
    ReviewCorrection,
    ReviewOccurrence,
)
from backend.v2.contexts.coaching.application.use_cases.correct_attendance import (
    COACH_CORRECTION_WINDOW,
)

#: Same 48h the coach side gives itself before a date stops being "recent".
MISSING_ATTENDANCE_GRACE = COACH_CORRECTION_WINDOW
MISSING_ATTENDANCE_LOOKBACK = timedelta(days=30)
CORRECTION_REVIEW_WINDOW = timedelta(days=14)


class AttendanceReview(BaseModel):
    model_config = {"frozen": True}

    missing: list[ReviewOccurrence]
    corrections: list[ReviewCorrection]


def needs_attendance(occurrence: ReviewOccurrence) -> bool:
    return (
        occurrence.status != "cancelled"
        and occurrence.enrolled_count > 0
        and occurrence.marked_count == 0
    )


class ListAttendanceReview:
    def __init__(
        self,
        *,
        reader: AttendanceReviewReader,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reader = reader
        self._now = clock

    async def missing(self) -> list[ReviewOccurrence]:
        now = self._now()
        rows = await self._reader.occurrences_between(
            now - MISSING_ATTENDANCE_LOOKBACK, now - MISSING_ATTENDANCE_GRACE
        )
        return sorted(
            (row for row in rows if needs_attendance(row)),
            key=lambda row: row.start_at,
            reverse=True,
        )

    async def execute(self) -> AttendanceReview:
        corrections = await self._reader.corrections_since(self._now() - CORRECTION_REVIEW_WINDOW)
        return AttendanceReview(
            missing=await self.missing(),
            corrections=sorted(corrections, key=lambda row: row.corrected_at, reverse=True),
        )
