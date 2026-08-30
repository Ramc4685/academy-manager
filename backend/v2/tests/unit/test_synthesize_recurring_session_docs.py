"""Direct unit coverage for ``synthesize_recurring_session_docs``.

The cancelled-template guard inside the synthesizer is unreachable from the
admin listing tests: ``_recurring_template_filter()`` already drops cancelled
templates in the Mongo query upstream. This module calls the pure function
head-on so the guard is genuinely exercised (#467).
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    synthesize_recurring_session_docs,
)

RANGE_START = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
RANGE_END = datetime(2026, 6, 30, 23, 59, tzinfo=UTC)


def _template(**overrides: object) -> dict[str, object]:
    doc: dict[str, object] = {
        # `_id` is read unconditionally by the synthesizer's session_id
        # `setdefault`, so a realistic Mongo doc must carry it.
        "_id": "oid-tpl-1",
        "academy_id": "academy-b",
        "session_id": "tpl-1",
        "name": "Recurring Junior",
        "location": "Court 1",
        "coach_id": "coach-1",
        "max_students": 10,
        "days_of_week": ["Mon", "Wed"],
        "start_time": "09:15",
        "end_time": "10:15",
        "timezone": "America/Chicago",
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
    }
    doc.update(overrides)
    return doc


def test_cancelled_template_synthesizes_no_rows() -> None:
    rows = synthesize_recurring_session_docs(
        [_template(status="cancelled")],
        range_start=RANGE_START,
        range_end=RANGE_END,
    )
    assert rows == []


def test_cancelled_template_is_skipped_alongside_live_templates() -> None:
    rows = synthesize_recurring_session_docs(
        [
            _template(session_id="tpl-cancelled", status="cancelled"),
            _template(session_id="tpl-live", status="active"),
        ],
        range_start=RANGE_START,
        range_end=RANGE_END,
        first_per_template=True,
    )
    assert [row["session_id"] for row in rows] == ["tpl-live"]


def test_status_less_and_active_templates_still_synthesize() -> None:
    """The guard must only catch "cancelled" — legacy docs have no status."""
    rows = synthesize_recurring_session_docs(
        [
            _template(session_id="tpl-no-status"),
            _template(session_id="tpl-null-status", status=None),
            _template(session_id="tpl-scheduled", status="scheduled"),
        ],
        range_start=RANGE_START,
        range_end=RANGE_END,
        first_per_template=True,
    )
    assert sorted(str(row["session_id"]) for row in rows) == [
        "tpl-no-status",
        "tpl-null-status",
        "tpl-scheduled",
    ]
