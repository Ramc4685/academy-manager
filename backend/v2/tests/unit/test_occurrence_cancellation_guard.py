"""Which dated classes may be called off (issue #671, domain guard)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.domain.errors import (
    OccurrenceAlreadyCancelled,
    OccurrenceNotCancellable,
    SessionCancelled,
)
from backend.v2.contexts.enrollment.domain.models import Session, SessionOccurrence
from backend.v2.contexts.enrollment.domain.occurrence_cancellation import (
    assert_occurrence_cancellable,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _occurrence(**overrides: object) -> SessionOccurrence:
    base: dict[str, object] = {
        "occurrence_id": "occ-1",
        "academy_id": "acad",
        "session_id": "sess-1",
        "start_at": NOW + timedelta(days=2),
        "end_at": NOW + timedelta(days=2, hours=1),
        "scheduled_coach_id": "coach-1",
    }
    base.update(overrides)
    return SessionOccurrence(**base)  # type: ignore[arg-type]


def _session(status: str = "scheduled") -> Session:
    return Session(
        session_id="sess-1",
        academy_id="acad",
        coach_id="coach-1",
        title="Beginner badminton",
        location="Court 1",
        start_at=NOW,
        end_at=NOW + timedelta(hours=1),
        capacity=10,
        status=status,  # type: ignore[arg-type]
    )


def test_future_scheduled_date_is_cancellable() -> None:
    assert_occurrence_cancellable(_occurrence(), session=_session(), now=NOW)


def test_missing_session_does_not_block_the_cancel() -> None:
    # A dated one-off whose template row is gone must still be cancellable:
    # the family is enrolled either way.
    assert_occurrence_cancellable(_occurrence(), session=None, now=NOW)


def test_already_cancelled_date_is_refused() -> None:
    with pytest.raises(OccurrenceAlreadyCancelled):
        assert_occurrence_cancellable(_occurrence(status="cancelled"), session=_session(), now=NOW)


def test_cancelled_session_is_refused() -> None:
    with pytest.raises(SessionCancelled):
        assert_occurrence_cancellable(_occurrence(), session=_session("cancelled"), now=NOW)


def test_past_date_is_refused() -> None:
    with pytest.raises(OccurrenceNotCancellable):
        assert_occurrence_cancellable(
            _occurrence(
                start_at=NOW - timedelta(days=1),
                end_at=NOW - timedelta(days=1) + timedelta(hours=1),
            ),
            session=_session(),
            now=NOW,
        )


def test_class_that_started_this_instant_is_refused() -> None:
    with pytest.raises(OccurrenceNotCancellable):
        assert_occurrence_cancellable(
            _occurrence(start_at=NOW, end_at=NOW + timedelta(hours=1)),
            session=_session(),
            now=NOW,
        )


def test_completed_future_row_is_refused() -> None:
    # Defensive: a row marked completed is history even if its clock says
    # otherwise (a corrected attendance sheet, a mis-stamped timezone).
    with pytest.raises(OccurrenceNotCancellable):
        assert_occurrence_cancellable(_occurrence(status="completed"), session=_session(), now=NOW)


def test_already_cancelled_wins_over_past() -> None:
    # The message an admin sees should name the state they can act on.
    with pytest.raises(OccurrenceAlreadyCancelled):
        assert_occurrence_cancellable(
            _occurrence(
                status="cancelled",
                start_at=NOW - timedelta(days=1),
                end_at=NOW - timedelta(days=1) + timedelta(hours=1),
            ),
            session=_session(),
            now=NOW,
        )
