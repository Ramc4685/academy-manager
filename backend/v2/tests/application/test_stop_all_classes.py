"""Issue #698: StopAllClasses composes over WithdrawEnrollment per row, and
the leaving report reads the resulting lifecycle events. Uses the shared
enrollment fakes (departures design contract §6.1) — no test-local copy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import WithdrawEnrollment
from backend.v2.contexts.enrollment.application.use_cases.leaving_report import (
    GetLeavingReport,
    LeavingReportRequest,
)
from backend.v2.contexts.enrollment.application.use_cases.stop_all_classes import (
    StopAllClasses,
    StopAllClassesCommand,
)
from backend.v2.contexts.enrollment.domain.models import Student
from backend.v2.tests.fixtures.enrollment_fakes import (
    FakeBillingSync,
    FakeEnrollmentEvents,
    FakeEnrollmentWriter,
    FakeSessionWriter,
    make_enrollment,
    make_session,
)


@dataclass
class _FakeDepartableQuery:
    """Wraps FakeEnrollmentWriter.rows for StopAllClassesQuery — a thin,
    test-local read shim, not a competing enrollment-writer fake."""

    writer: FakeEnrollmentWriter
    #: Extra "ghost" rows (enrollment_id not present in the writer) to
    #: simulate a row that fails inside WithdrawEnrollment.execute (its
    #: ``get`` returns None -> EnrollmentNotFound). Exercises the "partial
    #: failure is visible" requirement without a real concurrency race.
    ghost_rows: list = field(default_factory=list)

    async def departable_for_student(self, student_id: str):
        rows = [
            e
            for e in self.writer.rows.values()
            if e.student_id == student_id and e.status in {"active", "held", "paused"}
        ]
        return rows + [g for g in self.ghost_rows if g.student_id == student_id]


@dataclass
class _FakeSessionQuery:
    sessions: dict

    async def get(self, session_id: str):
        return self.sessions.get(session_id)


@dataclass
class _FakeStudentQuery:
    students: dict

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [self.students[sid] for sid in student_ids if sid in self.students]


def _withdraw(writer: FakeEnrollmentWriter, sessions: FakeSessionWriter, billing_sync, events):
    return WithdrawEnrollment(
        enrollments=writer,
        enrollment_events=events,
        billing=None,
        roster_notifier=None,
        billing_sync=billing_sync,
        sessions=sessions,
        outbox=None,
        occurrence_roster=None,
        scheduled_actions=None,
        clock=lambda: datetime(2026, 9, 9, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_stop_all_classes_drops_every_active_and_held_row_for_the_student():
    writer = FakeEnrollmentWriter(
        rows={
            "e1": make_enrollment("e1", student_id="stu-1", session_id="s1", status="active"),
            "e2": make_enrollment("e2", student_id="stu-1", session_id="s2", status="held"),
            # A different student's row must be untouched.
            "e3": make_enrollment("e3", student_id="stu-2", session_id="s1", status="active"),
            # Already withdrawn — not in the departable set, must be skipped.
            "e4": make_enrollment("e4", student_id="stu-1", session_id="s3", status="withdrawn"),
        }
    )
    sessions = FakeSessionWriter(
        sessions={"s1": make_session("s1"), "s2": make_session("s2"), "s3": make_session("s3")}
    )
    billing_sync = FakeBillingSync()
    events = FakeEnrollmentEvents()
    withdraw = _withdraw(writer, sessions, billing_sync, events)
    query = _FakeDepartableQuery(writer=writer)
    use_case = StopAllClasses(enrollments=query, withdraw=withdraw)

    result = await use_case.execute(
        StopAllClassesCommand(
            student_id="stu-1",
            effective_at=datetime(2026, 9, 9, tzinfo=UTC),
            outcome="adjustment",
            reason="Family moved away",
            actor_id="admin-1",
        )
    )

    assert result.dropped_count == 2
    assert result.failed_count == 0
    assert {r.enrollment_id for r in result.results} == {"e1", "e2"}
    assert writer.rows["e1"].status == "dropped"
    assert writer.rows["e2"].status == "dropped"
    # Untouched.
    assert writer.rows["e3"].status == "active"
    assert writer.rows["e4"].status == "withdrawn"

    # One lifecycle event PER ENROLLMENT, not one for the batch.
    withdrawn_events = [e for e in events.rows if e.event_type == "dropped"]
    assert len(withdrawn_events) == 2
    assert {e.enrollment_id for e in withdrawn_events} == {"e1", "e2"}

    # e1 was active (seat-holding) -> released; e2 was held (also
    # seat-holding) -> released. Exactly two release_seat calls, not more.
    assert sessions.release_calls == ["s1", "s2"]

    # Billing synced exactly once per dropped enrollment.
    assert len(billing_sync.calls) == 2
    assert {c["enrollment_id"] for c in billing_sync.calls} == {"e1", "e2"}


@pytest.mark.asyncio
async def test_stop_all_classes_partial_failure_is_visible_not_swallowed():
    """C11-equivalent: one row fails, the others still commit, and the
    failure is reported rather than silently dropped or rolled back."""
    writer = FakeEnrollmentWriter(
        rows={
            "e1": make_enrollment("e1", student_id="stu-1", session_id="s1", status="active"),
            "e3": make_enrollment("e3", student_id="stu-1", session_id="s1", status="active"),
        }
    )
    sessions = FakeSessionWriter(sessions={"s1": make_session("s1", capacity=5)})
    billing_sync = FakeBillingSync()
    events = FakeEnrollmentEvents()
    withdraw = _withdraw(writer, sessions, billing_sync, events)
    # "e2" is a ghost row: departable_for_student returns it, but the writer
    # has no such row, so WithdrawEnrollment.execute raises EnrollmentNotFound.
    ghost = make_enrollment("e2", student_id="stu-1", session_id="s1", status="active")
    query = _FakeDepartableQuery(writer=writer, ghost_rows=[ghost])
    use_case = StopAllClasses(enrollments=query, withdraw=withdraw)

    result = await use_case.execute(
        StopAllClassesCommand(
            student_id="stu-1",
            effective_at=datetime(2026, 9, 9, tzinfo=UTC),
            outcome="adjustment",
            reason="Family moved away",
            actor_id="admin-1",
        )
    )

    outcomes = {r.enrollment_id: r for r in result.results}
    assert outcomes["e1"].outcome == "dropped"
    assert outcomes["e3"].outcome == "dropped"
    assert outcomes["e2"].outcome == "failed"
    assert outcomes["e2"].error is not None
    assert result.dropped_count == 2
    assert result.failed_count == 1
    # No rollback of the successful drops.
    assert writer.rows["e1"].status == "dropped"
    assert writer.rows["e3"].status == "dropped"
    # Only the two real rows released a seat; the ghost never touched it.
    assert sessions.release_calls == ["s1", "s1"]


@pytest.mark.asyncio
async def test_leaving_report_reads_withdrawn_events_with_revenue_effect():
    events = FakeEnrollmentEvents()
    writer = FakeEnrollmentWriter(
        rows={"e1": make_enrollment("e1", student_id="stu-1", session_id="s1", status="active")}
    )
    sessions_writer = FakeSessionWriter(sessions={"s1": make_session("s1", amount_cents=15000)})
    billing_sync = FakeBillingSync()
    withdraw = _withdraw(writer, sessions_writer, billing_sync, events)

    from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
        WithdrawEnrollmentCommand,
    )

    await withdraw.execute(
        WithdrawEnrollmentCommand(
            enrollment_id="e1",
            effective_at=datetime(2026, 9, 9, tzinfo=UTC),
            outcome="adjustment",
            actor_id="admin-1",
            reason="Moved away",
        )
    )

    report = GetLeavingReport(
        events=events,
        sessions=_FakeSessionQuery({"s1": make_session("s1", amount_cents=15000)}),
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
    assert row.student_id == "stu-1"
    assert row.student_name == "Ada Lovelace"
    assert row.event_type == "dropped"
    assert row.is_system_action is False
    assert row.monthly_revenue_effect_cents == -15000


@pytest.mark.asyncio
async def test_leaving_report_marks_system_reclaim_actions():
    events = FakeEnrollmentEvents()
    events.rows.append(
        _make_lifecycle_event(
            event_type="hold_reclaimed",
            enrollment_id="e9",
            student_id="stu-9",
            session_id="s1",
            actor_id=None,
            occurred_at=datetime(2026, 9, 5, tzinfo=UTC),
        )
    )
    report = GetLeavingReport(
        events=events,
        sessions=_FakeSessionQuery({"s1": make_session("s1", amount_cents=10000)}),
        students=_FakeStudentQuery({}),
    )
    rows = await report.execute(
        LeavingReportRequest(
            start=datetime(2026, 9, 1, tzinfo=UTC),
            end=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    assert len(rows) == 1
    assert rows[0].is_system_action is True
    assert rows[0].student_name is None


def _make_lifecycle_event(**kwargs):
    from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent

    defaults = {
        "event_id": "ev-1",
        "academy_id": "acad",
        "effective_at": kwargs.get("occurred_at", datetime(2026, 9, 5, tzinfo=UTC)),
        "reason": "class full, longest-held reclaimed",
    }
    defaults.update(kwargs)
    return EnrollmentLifecycleEvent(**defaults)
