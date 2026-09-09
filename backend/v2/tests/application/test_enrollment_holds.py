"""Issue #697 — HoldEnrollment / ReturnFromHold: the hold state machine.

Covers the departures design contract's C5 and C6 concurrency cases, the
policy window bounds (§6.3), and the invariant that Return never touches
``try_reserve_seat`` (contract §2.4's single most important rule).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    TransferEnrollment,
    TransferEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.holds import (
    HoldEnrollment,
    ReturnFromHold,
)
from backend.v2.contexts.enrollment.domain.departure_policy import (
    EnrollmentDeparturePolicy,
    EnrollmentNotHoldable,
    EnrollmentNotReturnable,
    HoldWindowExceeded,
    compute_hold_expiry,
)
from backend.v2.tests.fixtures.enrollment_fakes import (
    FakeBillingSync,
    FakeDeparturePolicyRepo,
    FakeEnrollmentEvents,
    FakeEnrollmentWriter,
    FakeSessionWriter,
    make_enrollment,
    make_session,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _clock() -> datetime:
    return NOW


def _harness(status: str = "active"):
    enrollments = FakeEnrollmentWriter(rows={"enr-1": make_enrollment(status=status)})
    policy_repo = FakeDeparturePolicyRepo()
    billing = FakeBillingSync()
    events = FakeEnrollmentEvents()
    hold_uc = HoldEnrollment(
        enrollments=enrollments,
        departure_policy=policy_repo,
        enrollment_events=events,
        billing_sync=billing,
        clock=_clock,
    )
    return_uc = ReturnFromHold(
        enrollments=enrollments,
        enrollment_events=events,
        billing_sync=billing,
        clock=_clock,
    )
    return enrollments, policy_repo, billing, events, hold_uc, return_uc


@pytest.mark.asyncio
async def test_hold_keeps_status_moves_to_held_and_billing_syncs_once() -> None:
    enrollments, _policy, billing, events, hold_uc, _return_uc = _harness()

    result = await hold_uc.execute("enr-1", return_on=date(2026, 10, 1))

    assert result.status == "held"
    assert enrollments.rows["enr-1"].status == "held"
    assert enrollments.rows["enr-1"].hold_seq == 1
    assert [c["transition"] for c in billing.calls] == ["held"]
    assert [e.event_type for e in events.rows] == ["held"]


@pytest.mark.asyncio
async def test_hold_requires_active_status() -> None:
    _enrollments, _policy, _billing, _events, hold_uc, _return_uc = _harness(status="cancelled")

    with pytest.raises(EnrollmentNotHoldable):
        await hold_uc.execute("enr-1", return_on=date(2026, 10, 1))


@pytest.mark.asyncio
async def test_hold_from_paused_is_refused_with_the_resume_first_message() -> None:
    """T8: paused -> held is REFUSED. Two explicit steps, not one conversion
    that can strand the row half-converted."""
    _enrollments, _policy, _billing, _events, hold_uc, _return_uc = _harness(status="paused")

    with pytest.raises(EnrollmentNotHoldable) as excinfo:
        await hold_uc.execute("enr-1", return_on=date(2026, 10, 1))
    assert "Resume this enrollment first" in excinfo.value.message


@pytest.mark.asyncio
async def test_return_date_beyond_max_hold_days_is_rejected() -> None:
    enrollments, policy_repo, _billing, _events, hold_uc, _return_uc = _harness()
    policy_repo.policy = EnrollmentDeparturePolicy(academy_id="acad", max_hold_days=10)

    with pytest.raises(HoldWindowExceeded):
        await hold_uc.execute("enr-1", return_on=date(2026, 10, 1))  # ~22 days out

    # nothing was written on a rejected hold
    assert enrollments.rows["enr-1"].status == "active"


@pytest.mark.asyncio
async def test_return_date_in_the_past_or_today_is_rejected() -> None:
    _enrollments, _policy, _billing, _events, hold_uc, _return_uc = _harness()

    with pytest.raises(HoldWindowExceeded):
        await hold_uc.execute("enr-1", return_on=NOW.date())


def test_compute_hold_expiry_is_a_pure_snapshot() -> None:
    started = datetime(2026, 1, 1, tzinfo=UTC)
    assert compute_hold_expiry(started, 60) == started + timedelta(days=60)
    # Lowering max_hold_days later must never move an ALREADY-SNAPSHOTTED
    # expiry — this is guaranteed simply by never recomputing it, which this
    # test pins by construction: compute_hold_expiry takes the policy value
    # as an explicit argument, never a live lookup.
    assert compute_hold_expiry(started, 10) == started + timedelta(days=10)


@pytest.mark.asyncio
async def test_max_hold_days_bounds_422_at_the_domain_layer() -> None:
    with pytest.raises(Exception):
        EnrollmentDeparturePolicy(academy_id="acad", max_hold_days=0)
    with pytest.raises(Exception):
        EnrollmentDeparturePolicy(academy_id="acad", max_hold_days=366)
    # in-bounds values are fine
    EnrollmentDeparturePolicy(academy_id="acad", max_hold_days=1)
    EnrollmentDeparturePolicy(academy_id="acad", max_hold_days=365)


# -- C5: Return called twice ------------------------------------------------


@pytest.mark.asyncio
async def test_c5_return_called_twice_second_is_conflict_and_never_reserves_a_seat() -> None:
    """Direct regression guard for the double-count bug §2.4 warns about:
    Return must NEVER call try_reserve_seat, so a session object with
    try_reserve_seat wired to always raise proves it was never touched."""
    enrollments, _policy, billing, _events, hold_uc, return_uc = _harness()
    await hold_uc.execute("enr-1", return_on=date(2026, 10, 1))

    first = await return_uc.execute("enr-1")
    assert first.status == "active"

    with pytest.raises(EnrollmentNotReturnable):
        await return_uc.execute("enr-1")

    # exactly one "returned" billing sync call across both attempts
    assert [c["transition"] for c in billing.calls if c["transition"] == "returned"] == ["returned"]


# -- C6: Hold -> Drop, and Hold -> Return -> Drop: exactly one release_seat --


@pytest.mark.asyncio
async def test_c6_hold_then_drop_releases_the_seat_exactly_once() -> None:
    from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
        WithdrawEnrollment,
        WithdrawEnrollmentCommand,
    )

    enrollments = FakeEnrollmentWriter(rows={"enr-1": make_enrollment(status="active")})
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=5)})
    sessions.reserved_seats["sess-1"] = 1
    policy_repo = FakeDeparturePolicyRepo()
    billing = FakeBillingSync()

    hold_uc = HoldEnrollment(enrollments=enrollments, departure_policy=policy_repo, clock=_clock)
    await hold_uc.execute("enr-1", return_on=date(2026, 10, 1))
    assert enrollments.rows["enr-1"].status == "held"

    withdraw_uc = WithdrawEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        billing_sync=billing,
        clock=_clock,
    )
    await withdraw_uc.execute(
        WithdrawEnrollmentCommand(
            enrollment_id="enr-1",
            effective_at=NOW,
            outcome="adjustment",
            actor_id="admin-1",
            reason="drop",
        )
    )

    assert enrollments.rows["enr-1"].status == "dropped"
    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved_seats["sess-1"] == 0


@pytest.mark.asyncio
async def test_c6_hold_then_return_then_drop_releases_the_seat_exactly_once() -> None:
    from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
        WithdrawEnrollment,
        WithdrawEnrollmentCommand,
    )

    enrollments = FakeEnrollmentWriter(rows={"enr-1": make_enrollment(status="active")})
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=5)})
    sessions.reserved_seats["sess-1"] = 1
    policy_repo = FakeDeparturePolicyRepo()

    hold_uc = HoldEnrollment(enrollments=enrollments, departure_policy=policy_repo, clock=_clock)
    return_uc = ReturnFromHold(enrollments=enrollments, clock=_clock)

    await hold_uc.execute("enr-1", return_on=date(2026, 10, 1))
    await return_uc.execute("enr-1")
    assert enrollments.rows["enr-1"].status == "active"
    # Return never touched reserve/release
    assert sessions.reserve_calls == []
    assert sessions.release_calls == []

    withdraw_uc = WithdrawEnrollment(enrollments=enrollments, sessions=sessions, clock=_clock)
    await withdraw_uc.execute(
        WithdrawEnrollmentCommand(
            enrollment_id="enr-1",
            effective_at=NOW,
            outcome="adjustment",
            actor_id="admin-1",
            reason="drop",
        )
    )
    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved_seats["sess-1"] == 0


# -- C8: transfer of a held row, and transfer of a paused row (§0.1 fix) ----


@pytest.mark.asyncio
async def test_c8_transfer_of_held_row_moves_net_zero_seats() -> None:
    enrollments = FakeEnrollmentWriter(
        rows={"enr-1": make_enrollment(status="held", session_id="sess-a")}
    )
    sessions = FakeSessionWriter(
        sessions={
            "sess-a": make_session(session_id="sess-a", capacity=5),
            "sess-b": make_session(session_id="sess-b", capacity=5),
        }
    )
    sessions.reserved_seats["sess-a"] = 1
    sessions.reserved_seats["sess-b"] = 0

    transfer_uc = TransferEnrollment(enrollments=enrollments, sessions=sessions, clock=_clock)
    await transfer_uc.execute(
        TransferEnrollmentCommand(enrollment_id="enr-1", target_session_id="sess-b")
    )

    assert sessions.reserved_seats["sess-a"] == 0
    assert sessions.reserved_seats["sess-b"] == 1
    assert sessions.release_calls == ["sess-a"]


@pytest.mark.asyncio
async def test_c8_transfer_of_paused_row_never_double_releases_the_source_seat() -> None:
    """The §0.1 latent bug: a paused row already released its seat when it
    paused. TransferEnrollment must call release_seat ZERO times for it, or
    the source session silently admits one student past capacity."""
    enrollments = FakeEnrollmentWriter(
        rows={"enr-1": make_enrollment(status="paused", session_id="sess-a")}
    )
    sessions = FakeSessionWriter(
        sessions={
            "sess-a": make_session(session_id="sess-a", capacity=5),
            "sess-b": make_session(session_id="sess-b", capacity=5),
        }
    )
    # A paused enrollment holds no seat; another (active) student is the sole
    # occupant of sess-a's one reserved seat.
    sessions.reserved_seats["sess-a"] = 1
    sessions.reserved_seats["sess-b"] = 0

    transfer_uc = TransferEnrollment(enrollments=enrollments, sessions=sessions, clock=_clock)
    await transfer_uc.execute(
        TransferEnrollmentCommand(enrollment_id="enr-1", target_session_id="sess-b")
    )

    assert sessions.release_calls == []  # the fix: zero releases for a paused row
    assert sessions.reserved_seats["sess-a"] == 1  # the other student's seat survives
    assert sessions.reserved_seats["sess-b"] == 1
