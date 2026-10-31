"""Issue #775: a structured ``reason_code`` on the departure paths.

Drop (``WithdrawEnrollment``) and Stop-all-classes took a free-text
``reason`` and nothing else, so "why do families leave" was unanswerable
without reading every note by hand. The code is recorded ON the lifecycle
event, ALONGSIDE the free text — the note is where the detail lives and is
still required, the code is what the Left tab and the leaving report group
by.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    WithdrawEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.stop_all_classes import (
    StopAllClasses,
    StopAllClassesCommand,
)
from backend.v2.contexts.enrollment.domain.departure_policy import DEPARTURE_REASON_CODES
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.application.test_stop_all_classes import (
    _FakeDepartableQuery,
    _withdraw,
)
from backend.v2.tests.application.test_withdraw_single_path import EFFECTIVE, _build
from backend.v2.tests.fixtures.enrollment_fakes import (
    FakeBillingSync,
    FakeEnrollmentEvents,
    FakeEnrollmentWriter,
    FakeSessionWriter,
    make_enrollment,
    make_session,
)


def test_reason_codes_are_a_closed_vocabulary_with_an_escape_hatch():
    assert "other" in DEPARTURE_REASON_CODES
    # The drafted list from the free-text reasons the Drop dialog collects.
    assert {"moved_away", "cost", "schedule_conflict", "injury_or_health"} <= set(
        DEPARTURE_REASON_CODES
    )


@pytest.mark.asyncio
async def test_withdraw_records_the_reason_code_on_the_lifecycle_event():
    harness = _build("active")
    with tenant_scope("acad-1"):
        await harness.use_case.execute(
            WithdrawEnrollmentCommand(
                enrollment_id="enr-1",
                effective_at=EFFECTIVE,
                outcome="adjustment",
                actor_id="admin-1",
                reason="Dad took a job in Austin",
                reason_code="moved_away",
            )
        )

    dropped = [e for e in harness.events.rows if e.event_type == "dropped"]
    assert len(dropped) == 1
    assert dropped[0].reason_code == "moved_away"
    # The note is not replaced by the code.
    assert dropped[0].reason == "Dad took a job in Austin"


@pytest.mark.asyncio
async def test_withdraw_without_a_reason_code_still_works():
    """Every existing caller (hold reclaim, expiry, the legacy dialog) omits
    it; a departure with no code recorded is not a failed departure."""
    harness = _build("active")
    with tenant_scope("acad-1"):
        await harness.use_case.execute(
            WithdrawEnrollmentCommand(
                enrollment_id="enr-1",
                effective_at=EFFECTIVE,
                outcome="adjustment",
                actor_id="admin-1",
                reason="moving away",
            )
        )

    dropped = [e for e in harness.events.rows if e.event_type == "dropped"]
    assert dropped[0].reason_code is None


@pytest.mark.asyncio
async def test_stop_all_classes_stamps_one_reason_code_on_every_drop():
    writer = FakeEnrollmentWriter(
        rows={
            "e1": make_enrollment("e1", student_id="stu-1", session_id="s1", status="active"),
            "e2": make_enrollment("e2", student_id="stu-1", session_id="s2", status="active"),
        }
    )
    sessions = FakeSessionWriter(sessions={"s1": make_session("s1"), "s2": make_session("s2")})
    events = FakeEnrollmentEvents()
    use_case = StopAllClasses(
        enrollments=_FakeDepartableQuery(writer=writer),
        withdraw=_withdraw(writer, sessions, FakeBillingSync(), events),
    )

    with tenant_scope("acad-1"):
        await use_case.execute(
            StopAllClassesCommand(
                student_id="stu-1",
                effective_at=datetime(2026, 9, 9, tzinfo=UTC),
                outcome="adjustment",
                reason="Family moved away",
                reason_code="moved_away",
                actor_id="admin-1",
            )
        )

    dropped = [e for e in events.rows if e.event_type == "dropped"]
    assert len(dropped) == 2
    assert {e.reason_code for e in dropped} == {"moved_away"}
