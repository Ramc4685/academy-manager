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
    OccurrenceAlreadyCancelled,
    OccurrenceNotCancellable,
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
