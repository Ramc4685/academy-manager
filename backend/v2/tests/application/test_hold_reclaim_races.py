"""Departures design contract — C3, C4, C7, C10: the races the contract
names in §3.5 (the ordering table) and §3.7-§3.8 (crash recovery and
compensation), against the shared fakes in ``tests/fixtures/enrollment_fakes.py``.

Each test is written so that swapping the real CAS for an unconditional
overwrite (a status ``update_status`` instead of ``mark_*_if_*``, or a
``claim_longest_held`` that can return the same row twice) makes it FAIL,
not merely pass vacuously — see the contract's §6.1 warning about permissive
fakes hiding P1 money bugs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.seat_broker import SeatBroker
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    WithdrawEnrollment,
    WithdrawEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.holds import (
    ProcessStalledReclaims,
    ReturnFromHold,
)
from backend.v2.contexts.enrollment.domain.departure_policy import EnrollmentNotReturnable
from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotWithdrawable
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


# -- C3: reclaim claim vs Return, same row -----------------------------------


@pytest.mark.asyncio
async def test_c3_reclaim_wins_return_loses_with_named_error() -> None:
    """The claim CAS runs first: Return must see the row is no longer
    ``held`` and refuse, never silently resurrecting a dropped child."""
    enrollments = FakeEnrollmentWriter(
        rows={"held-1": make_enrollment("held-1", status="held", hold_started_at=NOW)}
    )
    holds = FakeHoldRepository(enrollments=enrollments)

    # The reclaim claim wins the race first.
    victim = await holds.claim_longest_held(session_id="sess-1", now=NOW, requested_by="x")
    assert victim is not None
    assert enrollments.rows["held-1"].status == "reclaim_pending"

    return_uc = ReturnFromHold(enrollments=enrollments, clock=lambda: NOW)
    with pytest.raises(EnrollmentNotReturnable):
        await return_uc.execute("held-1")
    # The row was not resurrected to active by the loser.
    assert enrollments.rows["held-1"].status == "reclaim_pending"


@pytest.mark.asyncio
async def test_c3_return_wins_reclaim_then_finds_no_candidate() -> None:
    """Return runs first: the claim CAS's filter (`status == "held"`) no
    longer matches, so the broker legitimately finds nothing to reclaim —
    reserved_seats is untouched in both orders."""
    enrollments = FakeEnrollmentWriter(
        rows={"held-1": make_enrollment("held-1", status="held", hold_started_at=NOW)}
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    holds = FakeHoldRepository(enrollments=enrollments)

    return_uc = ReturnFromHold(enrollments=enrollments, clock=lambda: NOW)
    result = await return_uc.execute("held-1")
    assert result.status == "active"

    broker = SeatBroker(
        sessions=sessions, holds=holds, departure_policy=FakeDeparturePolicyRepo(), clock=lambda: NOW
    )
    acquisition = await broker.acquire("sess-1", requested_by="y")
    assert acquisition.granted is False
    assert sessions.reserved_seats["sess-1"] == 1  # unchanged in this order too
    assert enrollments.rows["held-1"].status == "active"  # not touched by the failed claim


# -- C4: reclaim claim vs admin Drop, same row -------------------------------


@pytest.mark.asyncio
async def test_c4_reclaim_wins_drop_loses_with_conflict_and_no_side_effects() -> None:
    enrollments = FakeEnrollmentWriter(
        rows={"held-1": make_enrollment("held-1", status="held", hold_started_at=NOW)}
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()

    victim = await holds.claim_longest_held(session_id="sess-1", now=NOW, requested_by="x")
    assert victim is not None

    withdraw_uc = WithdrawEnrollment(enrollments=enrollments, sessions=sessions, billing_sync=billing, clock=lambda: NOW)
    with pytest.raises(EnrollmentNotWithdrawable):
        await withdraw_uc.execute(
            WithdrawEnrollmentCommand(
                enrollment_id="held-1",
                effective_at=NOW,
                outcome="adjustment",
                actor_id="admin-1",
                reason="drop",
            )
        )
    # The loser performed no billing sync and no seat release.
    assert billing.calls == []
    assert sessions.release_calls == []
    assert sessions.reserved_seats["sess-1"] == 1


@pytest.mark.asyncio
async def test_c4_drop_wins_reclaim_then_finds_no_candidate() -> None:
    enrollments = FakeEnrollmentWriter(
        rows={"held-1": make_enrollment("held-1", status="held", hold_started_at=NOW)}
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()

    withdraw_uc = WithdrawEnrollment(enrollments=enrollments, sessions=sessions, billing_sync=billing, clock=lambda: NOW)
    await withdraw_uc.execute(
        WithdrawEnrollmentCommand(
            enrollment_id="held-1",
            effective_at=NOW,
            outcome="adjustment",
            actor_id="admin-1",
            reason="drop",
        )
    )
    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved_seats["sess-1"] == 0

    broker = SeatBroker(
        sessions=sessions, holds=holds, departure_policy=FakeDeparturePolicyRepo(), clock=lambda: NOW
    )
    acquisition = await broker.acquire("sess-1", requested_by="y")
    # Drop already freed the seat AND removed the row from `held`, so the
    # broker's plain try_reserve_seat should succeed without any reclaim.
    assert acquisition.granted is True
    assert acquisition.via_reclaim is False
    assert sessions.reserved_seats["sess-1"] == 1
    assert sessions.release_calls == ["sess-1"]  # not called again


# -- C7: EditRosterAdd-shaped compensation after a reclaimed grant -----------


@pytest.mark.asyncio
async def test_c7_compensation_after_a_reclaimed_grant_releases_but_never_undoes_the_drop() -> None:
    """Simulates the EditRosterAdd contract: SeatBroker.acquire grants via
    reclaim, the caller's own enrollments.create then raises, and the
    caller compensates via SeatBroker.release — never a bare release_seat.
    """
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    enrollments = FakeEnrollmentWriter(
        rows={"held-1": make_enrollment("held-1", status="held", hold_started_at=NOW - timedelta(days=3))}
    )
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

    acquisition = await broker.acquire("sess-1", requested_by="roster_add:new-student")
    assert acquisition.granted and acquisition.via_reclaim
    assert enrollments.rows["held-1"].status == "dropped"
    assert len(notifier.reclaimed_calls) == 1

    # The caller's own write now fails (e.g. a duplicate-key on create).
    await broker.release(acquisition)

    # Seat accounting: released exactly once, count restored.
    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved_seats["sess-1"] == 0
    # The drop and its email are NOT retracted or resent.
    assert enrollments.rows["held-1"].status == "dropped"
    assert len(notifier.reclaimed_calls) == 1
    # An orphan event is the audit trail an admin needs.
    orphan_events = [e for e in events.rows if e.event_type == "hold_reclaim_orphaned"]
    assert len(orphan_events) == 1
    assert orphan_events[0].enrollment_id == "held-1"
    # No SECOND child was dropped to cover the same failed write.
    assert sum(1 for e in enrollments.rows.values() if e.status == "dropped") == 1


@pytest.mark.asyncio
async def test_c7_compensation_after_a_non_reclaimed_grant_releases_with_no_orphan_event() -> None:
    """When capacity was simply free (no reclaim), compensation is a plain
    release — no orphan event, because nobody was dropped for this seat."""
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=2)})
    enrollments = FakeEnrollmentWriter(rows={})
    holds = FakeHoldRepository(enrollments=enrollments)
    events = FakeEnrollmentEvents()
    broker = SeatBroker(
        sessions=sessions,
        holds=holds,
        departure_policy=FakeDeparturePolicyRepo(),
        enrollment_events=events,
        clock=lambda: NOW,
    )

    acquisition = await broker.acquire("sess-1", requested_by="roster_add:x")
    assert acquisition.granted and not acquisition.via_reclaim
    assert sessions.reserved_seats["sess-1"] == 1

    await broker.release(acquisition)

    assert sessions.reserved_seats["sess-1"] == 0
    assert events.rows == []


# -- C10: crash recovery between the claim CAS and finalize ------------------


@pytest.mark.asyncio
async def test_c10_stalled_reclaim_is_finalized_exactly_once_seat_count_unchanged() -> None:
    """A crash between `claim_longest_held` and `finalize` leaves a row
    `reclaim_pending`. The sweep must finalize it with `seat_disposition=
    "handed_over"` (no release_seat) and send exactly one email in total,
    even if the sweep runs twice (e.g. two overlapping job ticks)."""
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-1": make_enrollment(
                "held-1",
                status="reclaim_pending",
                session_id="sess-1",
                hold_started_at=NOW - timedelta(days=5),
                hold_reclaim_claimed_at=NOW - timedelta(minutes=30),
                hold_reclaim_for="roster_add:someone",
            )
        }
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1  # the reclaimed seat was already handed over
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()
    notifier = FakeHoldNotifier()
    events = FakeEnrollmentEvents()

    sweep = ProcessStalledReclaims(
        holds=holds, billing_sync=billing, notifier=notifier, enrollment_events=events, clock=lambda: NOW
    )

    finalized_first = await sweep.execute()
    assert finalized_first == 1
    assert enrollments.rows["held-1"].status == "dropped"
    assert sessions.release_calls == []  # handed_over — never released
    assert sessions.reserved_seats["sess-1"] == 1
    assert [c["transition"] for c in billing.calls] == ["dropped"]
    assert len(notifier.reclaimed_calls) == 1

    # A second, overlapping sweep tick finds nothing left to finalize.
    finalized_second = await sweep.execute()
    assert finalized_second == 0
    assert len(notifier.reclaimed_calls) == 1  # not sent again
    assert len(billing.calls) == 1  # not synced again
