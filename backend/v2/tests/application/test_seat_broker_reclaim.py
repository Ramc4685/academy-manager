"""Issue #697 — SeatBroker.acquire: the single demand point and reclaim.

Covers the departures design contract's C1, C2, C3, C4, C7, and a lite
version of C12 (the seat invariant, replayed over the fakes for a fixed
sequence rather than a full property-based generator — see the report for
what is not yet covered at full contract depth).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.seat_broker import SeatBroker
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    WithdrawEnrollment,
    WithdrawEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.holds import ReturnFromHold
from backend.v2.contexts.enrollment.domain.departure_policy import EnrollmentNotReturnable
from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotWithdrawable
from backend.v2.contexts.enrollment.domain.models import SEAT_HOLDING
from backend.v2.tests.fixtures.enrollment_fakes import (
    FakeBillingSync,
    FakeDeparturePolicyRepo,
    FakeEnrollmentEvents,
    FakeEnrollmentWriter,
    FakeHoldNotifier,
    FakeHoldRepository,
    FakeSessionWriter,
    make_enrollment,
    make_session,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _broker(enrollments: FakeEnrollmentWriter, sessions: FakeSessionWriter):
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()
    notifier = FakeHoldNotifier()
    events = FakeEnrollmentEvents()
    broker = SeatBroker(
        sessions=sessions,
        holds=holds,
        departure_policy=FakeDeparturePolicyRepo(),
        billing_sync=billing,
        notifier=notifier,
        enrollment_events=events,
        clock=lambda: NOW,
    )
    return broker, holds, billing, notifier, events


@pytest.mark.asyncio
async def test_c1_one_held_row_reclaimed_exactly_once_seat_count_unchanged() -> None:
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1  # full: the one held row
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-1": make_enrollment(
                "held-1", status="held", hold_started_at=NOW - timedelta(days=10)
            )
        }
    )
    broker, holds, billing, notifier, events = _broker(enrollments, sessions)

    acquisition = await broker.acquire("sess-1", requested_by="roster_add:new-student")

    assert acquisition.granted is True
    assert acquisition.via_reclaim is True
    assert acquisition.reclaimed_enrollment_id == "held-1"
    assert enrollments.rows["held-1"].status == "dropped"
    # reserved_seats untouched by the reclaim — the handover, not a
    # release-then-reserve.
    assert sessions.reserved_seats["sess-1"] == 1
    assert sessions.release_calls == []
    assert [c["transition"] for c in billing.calls] == ["dropped"]
    assert len(notifier.reclaimed_calls) == 1
    assert [e.event_type for e in events.rows] == ["hold_reclaimed"]

    # A second acquire on the now-empty session (no more holds, policy
    # cannot free anything further) is refused — one drop, one seat.
    second = await broker.acquire("sess-1", requested_by="roster_add:another-student")
    assert second.granted is False
    assert len(notifier.reclaimed_calls) == 1  # not sent again


@pytest.mark.asyncio
async def test_c2_two_held_rows_take_the_two_longest_in_order() -> None:
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=2)})
    sessions.reserved_seats["sess-1"] = 2
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-newer": make_enrollment(
                "held-newer",
                student_id="stu-newer",
                status="held",
                hold_started_at=NOW - timedelta(days=5),
            ),
            "held-older": make_enrollment(
                "held-older",
                student_id="stu-older",
                status="held",
                hold_started_at=NOW - timedelta(days=20),
            ),
        }
    )
    broker, holds, billing, notifier, events = _broker(enrollments, sessions)

    first = await broker.acquire("sess-1", requested_by="a")
    second = await broker.acquire("sess-1", requested_by="b")

    assert first.granted and second.granted
    # longest-held (held-older) is taken FIRST.
    assert first.reclaimed_enrollment_id == "held-older"
    assert second.reclaimed_enrollment_id == "held-newer"
    assert enrollments.rows["held-older"].status == "dropped"
    assert enrollments.rows["held-newer"].status == "dropped"
    assert sessions.reserved_seats["sess-1"] == 2  # unchanged across both reclaims
    assert len(notifier.reclaimed_calls) == 2


@pytest.mark.asyncio
async def test_acquire_grants_immediately_when_capacity_is_free_no_reclaim() -> None:
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=2)})
    sessions.reserved_seats["sess-1"] = 0
    enrollments = FakeEnrollmentWriter(rows={})
    broker, _holds, billing, notifier, _events = _broker(enrollments, sessions)

    acquisition = await broker.acquire("sess-1", requested_by="roster_add:x")

    assert acquisition.granted is True
    assert acquisition.via_reclaim is False
    assert sessions.reserved_seats["sess-1"] == 1
    assert billing.calls == []
    assert notifier.reclaimed_calls == []


@pytest.mark.asyncio
async def test_reclaim_policy_never_refuses_without_touching_holds() -> None:
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    enrollments = FakeEnrollmentWriter(
        rows={"held-1": make_enrollment("held-1", status="held", hold_started_at=NOW)}
    )
    holds = FakeHoldRepository(enrollments=enrollments)
    from backend.v2.contexts.enrollment.domain.departure_policy import EnrollmentDeparturePolicy

    policy_repo = FakeDeparturePolicyRepo(
        policy=EnrollmentDeparturePolicy(academy_id="acad", hold_reclaim_policy="never")
    )
    broker = SeatBroker(
        sessions=sessions, holds=holds, departure_policy=policy_repo, clock=lambda: NOW
    )

    acquisition = await broker.acquire("sess-1", requested_by="x")

    assert acquisition.granted is False
    assert enrollments.rows["held-1"].status == "held"  # untouched


# -- C12-lite: seat invariant over a small fixed sequence -------------------


@pytest.mark.asyncio
async def test_c12_lite_seat_invariant_holds_after_every_step() -> None:
    """A scaled-down version of the contract's strongest obligation: replay
    add -> hold -> reclaim-on-demand and assert reserved_seats ==
    |SEAT_HOLDING| after every step. Not the full randomized property test
    the contract asks for (see the report)."""
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    enrollments = FakeEnrollmentWriter(rows={})

    def invariant() -> None:
        holding = sum(1 for e in enrollments.rows.values() if e.status in SEAT_HOLDING)
        assert sessions.reserved_seats.get("sess-1", 0) == holding

    # 1. add student A — fills the one seat.
    ok = await sessions.try_reserve_seat("sess-1")
    assert ok
    enrollments.rows["a"] = make_enrollment("a", student_id="a", status="active")
    invariant()

    # 2. hold A.
    from backend.v2.contexts.enrollment.application.use_cases.holds import HoldEnrollment
    from datetime import date

    hold_uc = HoldEnrollment(
        enrollments=enrollments, departure_policy=FakeDeparturePolicyRepo(), clock=lambda: NOW
    )
    await hold_uc.execute("a", return_on=date(2026, 10, 1))
    invariant()

    # 3. student B wants the seat — reclaims A's hold (handover, net zero).
    broker, _holds, _billing, _notifier, _events = _broker(enrollments, sessions)
    acquisition = await broker.acquire("sess-1", requested_by="roster_add:b")
    assert acquisition.granted and acquisition.via_reclaim
    enrollments.rows["b"] = make_enrollment("b", student_id="b", status="active")
    invariant()

    # 4. B withdraws — releases the seat.
    from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
        WithdrawEnrollment,
        WithdrawEnrollmentCommand,
    )

    withdraw_uc = WithdrawEnrollment(enrollments=enrollments, sessions=sessions, clock=lambda: NOW)
    await withdraw_uc.execute(
        WithdrawEnrollmentCommand(
            enrollment_id="b", effective_at=NOW, outcome="adjustment", actor_id="admin", reason="x"
        )
    )
    invariant()
    assert sessions.reserved_seats["sess-1"] == 0


# -- C3: reclaim claim vs Return, same row -----------------------------------


@pytest.mark.asyncio
async def test_c3_reclaim_wins_return_then_fails_not_returnable() -> None:
    """If the broker's claim_longest_held wins the race, the row is already
    `reclaim_pending` by the time Return's CAS runs — Return MUST see a
    pre-image that is not `held` and refuse, never silently succeed on a
    row that no longer belongs to the family."""
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    enrollments = FakeEnrollmentWriter(
        rows={"enr-1": make_enrollment("enr-1", status="held", hold_started_at=NOW)}
    )
    broker, holds, billing, notifier, events = _broker(enrollments, sessions)
    return_uc = ReturnFromHold(enrollments=enrollments, clock=lambda: NOW)

    # Reclaim wins first.
    acquisition = await broker.acquire("sess-1", requested_by="roster_add:x")
    assert acquisition.granted and acquisition.via_reclaim
    assert enrollments.rows["enr-1"].status == "dropped"

    with pytest.raises(EnrollmentNotReturnable):
        await return_uc.execute("enr-1")

    # The seat was handed over, not released — Return's loss must not touch it.
    assert sessions.reserved_seats["sess-1"] == 1
    assert sessions.release_calls == []


@pytest.mark.asyncio
async def test_c3_return_wins_reclaim_then_finds_no_holds_left() -> None:
    """If Return wins first, the row leaves `held` before the broker's claim
    runs — claim_longest_held must find nothing and the broker must refuse,
    never invent a victim."""
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    enrollments = FakeEnrollmentWriter(
        rows={"enr-1": make_enrollment("enr-1", status="held", hold_started_at=NOW)}
    )
    broker, holds, billing, notifier, events = _broker(enrollments, sessions)
    return_uc = ReturnFromHold(enrollments=enrollments, clock=lambda: NOW)

    # Return wins first.
    result = await return_uc.execute("enr-1")
    assert result.status == "active"

    acquisition = await broker.acquire("sess-1", requested_by="roster_add:x")
    assert acquisition.granted is False
    assert acquisition.via_reclaim is False
    assert enrollments.rows["enr-1"].status == "active"  # untouched by the losing claim
    assert notifier.reclaimed_calls == []


# -- C4: reclaim claim vs admin Drop, same row -------------------------------


@pytest.mark.asyncio
async def test_c4_reclaim_wins_drop_then_conflicts() -> None:
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    enrollments = FakeEnrollmentWriter(
        rows={"enr-1": make_enrollment("enr-1", status="held", hold_started_at=NOW)}
    )
    broker, holds, billing, notifier, events = _broker(enrollments, sessions)
    withdraw_uc = WithdrawEnrollment(enrollments=enrollments, sessions=sessions, clock=lambda: NOW)

    acquisition = await broker.acquire("sess-1", requested_by="roster_add:x")
    assert acquisition.granted and acquisition.via_reclaim
    assert enrollments.rows["enr-1"].status == "dropped"

    with pytest.raises(EnrollmentNotWithdrawable):
        await withdraw_uc.execute(
            WithdrawEnrollmentCommand(
                enrollment_id="enr-1",
                effective_at=NOW,
                outcome="adjustment",
                actor_id="admin-1",
                reason="drop",
            )
        )
    # The loser must perform no seat accounting of its own — one seat total.
    assert sessions.release_calls == []
    assert sessions.reserved_seats["sess-1"] == 1


@pytest.mark.asyncio
async def test_c4_drop_wins_reclaim_then_finds_nothing_to_claim() -> None:
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    enrollments = FakeEnrollmentWriter(
        rows={"enr-1": make_enrollment("enr-1", status="held", hold_started_at=NOW)}
    )
    broker, holds, billing, notifier, events = _broker(enrollments, sessions)
    withdraw_uc = WithdrawEnrollment(enrollments=enrollments, sessions=sessions, clock=lambda: NOW)

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

    # A different concurrent request grabs the freed seat first (simulating
    # the ordinary path — the drop's own release is what feeds capacity, not
    # a reclaim), so by the time OUR broker call runs, capacity is full again
    # and there is no held row left, which is the scenario this case exists
    # to prove: reclaim must not invent a victim when Drop already won.
    assert await sessions.try_reserve_seat("sess-1") is True

    acquisition = await broker.acquire("sess-1", requested_by="roster_add:x")
    assert acquisition.granted is False
    assert acquisition.via_reclaim is False
    assert notifier.reclaimed_calls == []
    # No double release for the same drop.
    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved_seats["sess-1"] == 1
    assert enrollments.rows["enr-1"].status == "dropped"  # not resurrected


# -- C7: compensation when the requester's own write fails after a reclaim --


@pytest.mark.asyncio
async def test_c7_release_after_reclaim_orphans_the_victim_without_a_second_drop() -> None:
    """Mirrors EditRosterAdd's compensating block: the caller wins a seat via
    reclaim, then its own downstream write (e.g. enrollments.create) raises.
    SeatBroker.release must release the seat for SI, but it can never
    un-drop the victim — that email is already out."""
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-1": make_enrollment(
                "held-1", status="held", hold_started_at=NOW - timedelta(days=3)
            )
        }
    )
    broker, holds, billing, notifier, events = _broker(enrollments, sessions)

    acquisition = await broker.acquire("sess-1", requested_by="roster_add:new-student")
    assert acquisition.granted and acquisition.via_reclaim
    assert enrollments.rows["held-1"].status == "dropped"
    assert [e.event_type for e in events.rows] == ["hold_reclaimed"]

    # The requester's own write (e.g. enrollments.create) now raises; it
    # compensates via broker.release, exactly as EditRosterAdd's existing
    # compensating block does today for a plain reserve.
    await broker.release(acquisition)

    # SI holds regardless of the reclaim: the seat is released.
    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved_seats["sess-1"] == 0
    # The victim stays dropped — it is never un-dropped — but an orphan
    # event records that the seat went nowhere.
    assert enrollments.rows["held-1"].status == "dropped"
    event_types = [e.event_type for e in events.rows]
    assert event_types == ["hold_reclaimed", "hold_reclaim_orphaned"]
    # The reclaim notice was already sent and must not be retracted.
    assert len(notifier.reclaimed_calls) == 1


@pytest.mark.asyncio
async def test_c7_release_after_a_plain_reserve_is_a_bare_release_no_orphan_event() -> None:
    """When acquire granted WITHOUT a reclaim, release must be a bare
    release_seat — no orphan bookkeeping, because nobody was dropped."""
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=2)})
    sessions.reserved_seats["sess-1"] = 0
    enrollments = FakeEnrollmentWriter(rows={})
    broker, holds, billing, notifier, events = _broker(enrollments, sessions)

    acquisition = await broker.acquire("sess-1", requested_by="roster_add:x")
    assert acquisition.granted and not acquisition.via_reclaim

    await broker.release(acquisition)

    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved_seats["sess-1"] == 0
    assert events.rows == []  # no orphan event for a non-reclaim release
