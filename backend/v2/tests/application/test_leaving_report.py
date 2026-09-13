"""Issue #744: the Delete-enrollment route records lifecycle events with
``event_type="removed"`` (``CancelEnrollmentCommand``, ``sessions_routes.py``
``DELETE /enrollments/{id}``), but the leaving report's departure filter
didn't include that value, so removed enrollments never showed up in the
report. Uses the shared enrollment fakes (departures design contract §6.1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.leaving_report import (
    DEPARTURE_EVENT_TYPES,
    GetLeavingReport,
    LeavingReportRequest,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models import Student
from backend.v2.tests.fixtures.enrollment_fakes import FakeEnrollmentEvents, make_session


class _FakeSessionQuery:
    def __init__(self, sessions: dict) -> None:
        self.sessions = sessions

    async def get(self, session_id: str):
        return self.sessions.get(session_id)


class _FakeStudentQuery:
    def __init__(self, students: dict) -> None:
        self.students = students

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [self.students[sid] for sid in student_ids if sid in self.students]


def test_departure_event_types_includes_removed():
    assert "removed" in DEPARTURE_EVENT_TYPES
    # Regression guard: the fix must not narrow the existing set.
    assert {
        "withdrawn",
        "dropped",
        "hold_reclaimed",
        "hold_expired",
        "hold_reclaim_orphaned",
        "deleted",
    } <= DEPARTURE_EVENT_TYPES


@pytest.mark.asyncio
async def test_removed_enrollment_appears_in_leaving_report():
    events = FakeEnrollmentEvents()
    events.rows.append(
        EnrollmentLifecycleEvent(
            event_id="ev-removed-1",
            academy_id="acad",
            enrollment_id="e1",
            student_id="stu-1",
            session_id="s1",
            event_type="removed",
            occurred_at=datetime(2026, 9, 5, tzinfo=UTC),
            effective_at=datetime(2026, 9, 5, tzinfo=UTC),
            reason="Removed by admin",
            actor_id="admin-1",
        )
    )
    report = GetLeavingReport(
        events=events,
        sessions=_FakeSessionQuery({"s1": make_session("s1", amount_cents=10000)}),
        students=_FakeStudentQuery(
            {
                "stu-1": Student(
                    student_id="stu-1",
                    academy_id="acad",
                    parent_id="parent-1",
                    full_name="Ada Lovelace",
                )
            }
        ),
    )

    rows = await report.execute(
        LeavingReportRequest(
            start=datetime(2026, 9, 1, tzinfo=UTC),
            end=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == "removed"
    assert row.reason == "Removed by admin"
    assert row.student_id == "stu-1"
    assert row.student_name == "Ada Lovelace"
    assert row.is_system_action is False
    assert row.monthly_revenue_effect_cents == -10000
