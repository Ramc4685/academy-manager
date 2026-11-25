"""Admin attendance review rules (Inbox "Attendance" tab)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.v2.contexts.coaching.application.ports import ReviewCorrection, ReviewOccurrence
from backend.v2.contexts.coaching.application.use_cases.attendance_review import (
    CORRECTION_REVIEW_WINDOW,
    MISSING_ATTENDANCE_GRACE,
    MISSING_ATTENDANCE_LOOKBACK,
    ListAttendanceReview,
)

NOW = datetime(2026, 11, 22, 18, 0, tzinfo=UTC)


def _occ(occurrence_id: str, start_at: datetime, **overrides: object) -> ReviewOccurrence:
    fields: dict[str, object] = {
        "occurrence_id": occurrence_id,
        "session_id": "sess-1",
        "session_name": "Juniors",
        "start_at": start_at,
        "status": "scheduled",
        "enrolled_count": 4,
        "marked_count": 0,
    }
    fields.update(overrides)
    return ReviewOccurrence(**fields)  # type: ignore[arg-type]


def _correction(attendance_id: str, corrected_at: datetime) -> ReviewCorrection:
    return ReviewCorrection(
        attendance_id=attendance_id,
        occurrence_id="occ-1",
        session_id="sess-1",
        session_name="Juniors",
        start_at=NOW - timedelta(days=3),
        student_id="stu-1",
        student_name="Ava Pine",
        status="voided",
        previous_status="present",
        corrected_at=corrected_at,
        corrected_by_name="Owner",
        reason="Wrong class",
    )


class FakeReader:
    """Honours the reader contract: only dates in ``[start, end)``, no cancelled."""

    def __init__(
        self,
        occurrences: list[ReviewOccurrence],
        corrections: list[ReviewCorrection] | None = None,
    ) -> None:
        self.occurrences = occurrences
        self.corrections = corrections or []
        self.windows: list[tuple[datetime, datetime]] = []
        self.correction_since: datetime | None = None

    async def occurrences_between(self, start: datetime, end: datetime) -> list[ReviewOccurrence]:
        self.windows.append((start, end))
        return [
            row
            for row in self.occurrences
            if start <= row.start_at < end and row.status != "cancelled"
        ]

    async def corrections_since(self, since: datetime) -> list[ReviewCorrection]:
        self.correction_since = since
        return [row for row in self.corrections if row.corrected_at >= since]


def _use_case(reader: FakeReader) -> ListAttendanceReview:
    return ListAttendanceReview(reader=reader, clock=lambda: NOW)


async def test_grace_period_is_the_coach_48h_window() -> None:
    assert MISSING_ATTENDANCE_GRACE == timedelta(hours=48)
    inside_grace = _occ("occ-recent", NOW - timedelta(hours=47))
    just_past = _occ("occ-old", NOW - timedelta(hours=49))
    reader = FakeReader([inside_grace, just_past])

    missing = await _use_case(reader).missing()

    assert [row.occurrence_id for row in missing] == ["occ-old"]
    assert reader.windows == [(NOW - MISSING_ATTENDANCE_LOOKBACK, NOW - MISSING_ATTENDANCE_GRACE)]


async def test_cancelled_zero_enrollment_and_marked_dates_are_not_missing() -> None:
    start = NOW - timedelta(days=3)
    reader = FakeReader(
        [
            _occ("occ-cancelled", start, status="cancelled"),
            _occ("occ-empty-roster", start, enrolled_count=0),
            _occ("occ-marked", start, marked_count=1),
            _occ("occ-missing", start),
        ]
    )

    missing = await _use_case(reader).missing()

    assert [row.occurrence_id for row in missing] == ["occ-missing"]


async def test_cancelled_is_excluded_even_if_a_reader_returns_it() -> None:
    reader = FakeReader([])
    reader.occurrences_between = _returns(  # type: ignore[method-assign]
        [_occ("occ-cancelled", NOW - timedelta(days=3), status="cancelled")]
    )

    assert await _use_case(reader).missing() == []


def _returns(rows: list[ReviewOccurrence]):
    async def read(_start: datetime, _end: datetime) -> list[ReviewOccurrence]:
        return rows

    return read


async def test_dates_past_the_lookback_drop_off_and_newest_comes_first() -> None:
    reader = FakeReader(
        [
            _occ("occ-ancient", NOW - MISSING_ATTENDANCE_LOOKBACK - timedelta(hours=1)),
            _occ("occ-5d", NOW - timedelta(days=5)),
            _occ("occ-3d", NOW - timedelta(days=3)),
        ]
    )

    missing = await _use_case(reader).missing()

    assert [row.occurrence_id for row in missing] == ["occ-3d", "occ-5d"]


async def test_corrections_cover_the_review_window_newest_first() -> None:
    reader = FakeReader(
        [],
        corrections=[
            _correction("att-old", NOW - CORRECTION_REVIEW_WINDOW - timedelta(hours=1)),
            _correction("att-2d", NOW - timedelta(days=2)),
            _correction("att-1h", NOW - timedelta(hours=1)),
        ],
    )

    review = await _use_case(reader).execute()

    assert [row.attendance_id for row in review.corrections] == ["att-1h", "att-2d"]
    assert reader.correction_since == NOW - CORRECTION_REVIEW_WINDOW
    assert review.missing == []
