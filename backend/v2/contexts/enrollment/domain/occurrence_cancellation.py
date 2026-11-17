"""Cancelling ONE dated class (issue #671): the invariant, not the workflow.

A rain-out, a sick coach or a holiday calls off a single date. The rules
that decide whether that is allowed live here so every writer — the admin
route today, a coach route or a bulk holiday tool later — refuses the same
things for the same reasons:

* an already-cancelled date cannot be cancelled again (the second click must
  not re-issue credits or re-notify families);
* a class that has started or finished is history — attendance, payroll and
  the family's invoice already treat it as having happened;
* a date on a cancelled session is moot: the whole class is gone.
"""

from __future__ import annotations

from datetime import datetime

from backend.v2.contexts.enrollment.domain.errors import (
    MissedClassHadAttendance,
    OccurrenceAlreadyCancelled,
    OccurrenceNotCancellable,
    OccurrenceNotPast,
    SessionCancelled,
)
from backend.v2.contexts.enrollment.domain.models import Session, SessionOccurrence


def assert_occurrence_cancellable(
    occurrence: SessionOccurrence,
    *,
    session: Session | None,
    now: datetime,
) -> None:
    """Raise the domain error that explains why this date cannot be cancelled."""
    if occurrence.status == "cancelled":
        raise OccurrenceAlreadyCancelled(
            "this class date is already cancelled",
            occurrence_id=occurrence.occurrence_id,
        )
    if session is not None and session.status == "cancelled":
        raise SessionCancelled(
            "the whole session is cancelled",
            session_id=session.session_id,
        )
    if occurrence.status == "completed" or occurrence.start_at <= now:
        raise OccurrenceNotCancellable(
            "a class that has already started cannot be cancelled",
            occurrence_id=occurrence.occurrence_id,
        )


def assert_missed_class_creditable(
    occurrence: SessionOccurrence,
    *,
    session: Session | None,
    now: datetime,
    present_count: int | None,
) -> None:
    """A PAST date the academy found out too late was a no-class day (#1207).

    ``present_count`` is the students marked present or late; ``None`` means
    attendance could not be read, which is not proof nobody came.
    """
    if occurrence.status == "cancelled":
        raise OccurrenceAlreadyCancelled(
            "this class date is already cancelled",
            occurrence_id=occurrence.occurrence_id,
        )
    if session is not None and session.status == "cancelled":
        raise SessionCancelled("the whole session is cancelled", session_id=session.session_id)
    if occurrence.end_at > now:
        # A class still in progress has not been missed yet (#1207 review).
        raise OccurrenceNotPast(
            "this class has not finished yet; call a future date off instead",
            occurrence_id=occurrence.occurrence_id,
        )
    if occurrence.status == "completed":
        raise OccurrenceNotCancellable(
            "this class is marked as held, so it cannot be credited as missed",
            occurrence_id=occurrence.occurrence_id,
        )
    if present_count is None:
        raise MissedClassHadAttendance(
            "attendance for this date could not be checked, so it cannot be credited",
            occurrence_id=occurrence.occurrence_id,
        )
    if present_count > 0:
        raise MissedClassHadAttendance(
            f"{present_count} student(s) were marked present that day, so the class ran; "
            "correct the attendance first if that is wrong",
            occurrence_id=occurrence.occurrence_id,
        )
