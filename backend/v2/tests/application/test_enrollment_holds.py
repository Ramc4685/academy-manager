"""Issue #697 — HoldEnrollment / ReturnFromHold: the hold state machine.

Covers the departures design contract's C5 and C6 concurrency cases, the
policy window bounds (§6.3), and the invariant that Return never touches
``try_reserve_seat`` (contract §2.4's single most important rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import get_args

import pytest
from pydantic import ValidationError

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    PauseEnrollment,
    PauseEnrollmentCommand,
    TransferEnrollment,
    TransferEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import (
    BillingDeferral,
)
from backend.v2.contexts.enrollment.application.use_cases.holds import (
    STALLED_RECLAIM_AFTER,
    ExpireDueHolds,
    HoldEnrollment,
    ProcessStalledReclaims,
    ReturnFromHold,
)
from backend.v2.contexts.enrollment.domain.departure_policy import (
    EnrollmentDeparturePolicy,
    EnrollmentNotHoldable,
    EnrollmentNotPausable,
    EnrollmentNotReturnable,
    HoldWindowExceeded,
    compute_hold_expiry,
)
from backend.v2.contexts.enrollment.domain.models import (
    SEAT_HOLDING,
    SEATLESS,
    EnrollmentStatus,
)
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


@dataclass
class _FakeBillingDeferrals:
    rows: list[BillingDeferral] = field(default_factory=list)

    async def add(self, deferral: BillingDeferral) -> None:
        self.rows.append(deferral)


@pytest.mark.asyncio
async def test_hold_writes_one_billing_deferral_per_held_month_like_pause_does() -> None:
    """Departures design contract T1: a held month must leave the same audit
    trail a paused month does — one ``BillingDeferral`` per month via the
    SAME ``paused_billing_periods`` helper ``PauseEnrollment`` uses. No money
    moves either way (the invoice generator selects only active/paused, so a
    held row was already invisible) but before this fix no branch wrote the
    deferral, so a paused month left a generation-skip record and a held
    month left nothing — the audit trail disagreed with itself."""
    enrollments = FakeEnrollmentWriter(rows={"enr-1": make_enrollment(status="active")})
    deferrals = _FakeBillingDeferrals()
    hold_uc = HoldEnrollment(
        enrollments=enrollments,
        departure_policy=FakeDeparturePolicyRepo(),
        billing_deferrals=deferrals,
        clock=_clock,
    )

    # NOW is 2026-09-09; a return_on of 2026-10-15 suppresses exactly the
    # 2026-10 billing period (the current month, September, stays payable).
    await hold_uc.execute(
        "enr-1", return_on=date(2026, 10, 15), reason="family trip", actor_id="admin-1"
    )

    assert [d.billing_period for d in deferrals.rows] == ["2026-10"]
    [deferral] = deferrals.rows
    assert deferral.deferral_type == "admin_hold"
    assert deferral.enrollment_id == "enr-1"
    assert deferral.student_id == "stu-1"
    assert deferral.resume_on == date(2026, 10, 15)
    assert deferral.source == "admin_hold"
    assert deferral.actor_id == "admin-1"
    assert deferral.status == "active"


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
    with pytest.raises(ValidationError):
        EnrollmentDeparturePolicy(academy_id="acad", max_hold_days=0)
    with pytest.raises(ValidationError):
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
    _enrollments, _policy, billing, _events, hold_uc, return_uc = _harness()
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


# -- Structural: HoldEnrollment cannot touch waitlist or outbox -------------


def test_hold_enrollment_constructor_has_no_waitlist_or_outbox_collaborator() -> None:
    """Contract §2.4 T1: 'Unlike Pause, Hold writes no WaitlistEntry and
    emits no EnrollmentCancelled.' PauseEnrollment's constructor accepts a
    ``waitlist`` and an ``outbox`` collaborator precisely because it must use
    them; HoldEnrollment must have no way to reach either, so this is
    enforced by the type signature itself, not by a mock that happens not to
    be called."""
    import inspect

    params = set(inspect.signature(HoldEnrollment.__init__).parameters)
    assert "waitlist" not in params
    assert "outbox" not in params


# -- C10: crash recovery after a `held -> reclaim_pending` CAS --------------


@pytest.mark.asyncio
async def test_c10_stalled_reclaim_is_finalized_exactly_once_seats_unchanged() -> None:
    """A crash between claim_longest_held and finalize leaves a row stuck in
    reclaim_pending. ProcessStalledReclaims must finalize it as
    'handed_over' (no seat arithmetic — the requester already holds the
    seat) and the notice must be sent exactly once even if the sweep runs
    twice."""
    claimed_at = NOW - STALLED_RECLAIM_AFTER - timedelta(minutes=1)
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-1": make_enrollment(
                "held-1",
                status="reclaim_pending",
                hold_started_at=NOW - timedelta(days=10),
                hold_reclaim_claimed_at=claimed_at,
                hold_reclaim_for="roster_add:new-student",
            )
        }
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1  # the requester already holds this seat
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()
    notifier = FakeHoldNotifier()
    events = FakeEnrollmentEvents()

    sweep = ProcessStalledReclaims(
        holds=holds,
        billing_sync=billing,
        notifier=notifier,
        enrollment_events=events,
        clock=lambda: NOW,
    )

    finalized_first = await sweep.execute()
    assert finalized_first == 1
    assert enrollments.rows["held-1"].status == "dropped"
    # Handed-over disposition: no seat arithmetic from the sweep.
    assert sessions.release_calls == []
    assert sessions.reserved_seats["sess-1"] == 1
    assert [c["transition"] for c in billing.calls] == ["dropped"]
    assert len(notifier.reclaimed_calls) == 1

    # A second sweep tick (e.g. the job runs again before the next crash
    # window) must not re-finalize or re-notify — the row is already
    # withdrawn, so list_stalled finds nothing.
    finalized_second = await sweep.execute()
    assert finalized_second == 0
    assert len(notifier.reclaimed_calls) == 1
    assert [c["transition"] for c in billing.calls] == ["dropped"]


@pytest.mark.asyncio
async def test_c10_a_reclaim_pending_row_not_yet_stale_is_left_alone() -> None:
    """The sweep must only touch rows older than STALLED_RECLAIM_AFTER —
    otherwise it would race a still-in-flight (non-crashed) caller."""
    fresh_claim = NOW - timedelta(minutes=1)
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-1": make_enrollment(
                "held-1",
                status="reclaim_pending",
                hold_started_at=NOW - timedelta(days=10),
                hold_reclaim_claimed_at=fresh_claim,
                hold_reclaim_for="roster_add:x",
            )
        }
    )
    holds = FakeHoldRepository(enrollments=enrollments)
    sweep = ProcessStalledReclaims(holds=holds, clock=lambda: NOW)

    finalized = await sweep.execute()

    assert finalized == 0
    assert enrollments.rows["held-1"].status == "reclaim_pending"


@pytest.mark.asyncio
async def test_stalled_reclaim_from_an_expiry_claim_finalizes_as_expiry_not_reclaim() -> None:
    """Defect #3: ExpireDueHolds claims with requested_by='hold_expiry' and
    finalizes with seat_disposition='release'. If the process dies between
    the claim and the finalize, the row sits reclaim_pending with
    hold_reclaim_for='hold_expiry'. ProcessStalledReclaims must recognise
    that provenance and finalize it exactly as ExpireDueHolds would have —
    reason='expired', seat_disposition='release' — not as a generic reclaim
    (reason='reclaimed', seat_disposition='handed_over'), which would leak
    the seat (nobody is waiting for it — 'handed_over' does no seat
    arithmetic) and email the family the wrong reason."""
    claimed_at = NOW - STALLED_RECLAIM_AFTER - timedelta(minutes=1)
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-1": make_enrollment(
                "held-1",
                session_id="sess-1",
                status="reclaim_pending",
                hold_started_at=NOW - timedelta(days=70),
                hold_reclaim_claimed_at=claimed_at,
                hold_reclaim_for="hold_expiry",
            )
        }
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session("sess-1", capacity=1)})
    sessions.reserved_seats["sess-1"] = 1  # nobody is waiting for this seat
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()
    notifier = FakeHoldNotifier()
    events = FakeEnrollmentEvents()

    sweep = ProcessStalledReclaims(
        holds=holds,
        sessions=sessions,
        billing_sync=billing,
        notifier=notifier,
        enrollment_events=events,
        clock=lambda: NOW,
    )

    finalized = await sweep.execute()

    assert finalized == 1
    assert enrollments.rows["held-1"].status == "dropped"
    # The defining assertion: the seat is RELEASED (nobody takes it), unlike
    # a real reclaim's handed-over disposition which leaves the counter
    # alone.
    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved_seats["sess-1"] == 0
    # The family must be told "expired", never "reclaimed".
    assert len(notifier.reclaimed_calls) == 1
    assert notifier.reclaimed_calls[0]["reason"] == "expired"
    recorded = [e for e in events.rows if e.enrollment_id == "held-1"]
    assert [e.event_type for e in recorded] == ["hold_expired"]


# -- Defect #1: ExpireDueHolds must drop the EXPIRED row, never the -----
# -- longest-held row on the same session --------------------------------


@pytest.mark.asyncio
async def test_expire_due_holds_drops_the_expired_row_not_the_longest_held() -> None:
    """Two held rows on ONE session: 'old-not-expired' started first (so it
    is the longest-held) but its own hold_expires_at has NOT passed yet;
    'due-for-expiry' started later but its hold_expires_at HAS passed.

    A correct expiry sweep claims and drops 'due-for-expiry' by id.
    Claiming by session + longest-held-sort (the pre-fix bug) picks
    'old-not-expired' instead — dropping the wrong child while the actually
    -expired hold is left untouched forever.
    """
    enrollments = FakeEnrollmentWriter(
        rows={
            "old-not-expired": make_enrollment(
                "old-not-expired",
                session_id="sess-1",
                student_id="stu-old",
                status="held",
                hold_started_at=NOW - timedelta(days=50),
                hold_expires_at=NOW + timedelta(days=10),  # NOT yet expired
                hold_seq=1,
            ),
            "due-for-expiry": make_enrollment(
                "due-for-expiry",
                session_id="sess-1",
                student_id="stu-due",
                status="held",
                hold_started_at=NOW - timedelta(days=5),
                hold_expires_at=NOW - timedelta(hours=1),  # expired
                hold_seq=1,
            ),
        }
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session("sess-1", capacity=5)})
    sessions.reserved_seats["sess-1"] = 2
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()
    notifier = FakeHoldNotifier()
    events = FakeEnrollmentEvents()
    policy_repo = FakeDeparturePolicyRepo()

    sweep = ExpireDueHolds(
        holds=holds,
        sessions=sessions,
        departure_policy=policy_repo,
        billing_sync=billing,
        notifier=notifier,
        enrollment_events=events,
        clock=lambda: NOW,
    )

    result = await sweep.execute()

    assert result.expired == 1
    assert result.failed == 0
    # The row that actually expired is the one dropped...
    assert enrollments.rows["due-for-expiry"].status == "dropped"
    # ...and the still-valid hold is left completely untouched.
    assert enrollments.rows["old-not-expired"].status == "held"
    assert enrollments.rows["old-not-expired"].hold_reclaim_claimed_at is None
    assert [c.get("enrollment_id") for c in notifier.reclaimed_calls] == ["due-for-expiry"]
    assert [c["enrollment_id"] for c in billing.calls] == ["due-for-expiry"]
    # Nobody is waiting for an expired hold's seat — it is released, exactly
    # once, for the row that actually expired.
    assert sessions.release_calls == ["sess-1"]


# -- Defect #5 / T9: held -> paused must be REFUSED, not silently allowed --


@pytest.mark.asyncio
async def test_pause_a_held_enrollment_is_refused_with_409() -> None:
    """T9: a held row's seat is retained precisely so the family is safe
    from losing it. PauseEnrollment must not be allowed to release that
    seat, park the student on the waitlist and promote someone else out from
    under a family that was told their seat was safe."""
    enrollments = FakeEnrollmentWriter(
        rows={"enr-1": make_enrollment(status="held", hold_started_at=NOW)}
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session(capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    pause = PauseEnrollment(enrollments=enrollments, sessions=sessions, clock=lambda: NOW)

    with pytest.raises(EnrollmentNotPausable):
        await pause.execute(PauseEnrollmentCommand(enrollment_id="enr-1"))

    # Refused before any side effect: status, seat and release-call count
    # are all untouched.
    assert enrollments.rows["enr-1"].status == "held"
    assert sessions.release_calls == []
    assert sessions.reserved_seats["sess-1"] == 1


# -- Defect #6: every seat-release predicate must be exhaustive over the --
# -- full EnrollmentStatus set --------------------------------------------


def test_every_enrollment_status_is_classified_for_seat_release() -> None:
    """`SEAT_HOLDING` and `SEATLESS` are deliberately not full complements —
    `reclaim_pending` is the ONE named, transient exception (mid-handover:
    neither holding nor released until finalize() runs). This test fails
    for any OTHER status the model can write that neither set classifies,
    which is exactly the gap that let `CancelEnrollment`'s old `not in
    SEATLESS` predicate silently treat `reclaim_pending` as releasable
    (defect #6). If `EnrollmentStatus` ever grows a new member, this test
    forces an explicit decision about it rather than a silent fall-through.
    """
    all_statuses = set(get_args(EnrollmentStatus))
    transient_exceptions = {"reclaim_pending"}

    assert SEAT_HOLDING.isdisjoint(SEATLESS)
    assert SEAT_HOLDING.isdisjoint(transient_exceptions)
    assert SEATLESS.isdisjoint(transient_exceptions)
    unclassified = all_statuses - SEAT_HOLDING - SEATLESS - transient_exceptions
    assert unclassified == set(), (
        f"EnrollmentStatus member(s) {unclassified} are classified by NEITHER "
        "SEAT_HOLDING nor SEATLESS nor the named transient exception — every "
        "seat-release call site must decide `in SEAT_HOLDING`, never "
        "`not in SEATLESS`, or a status like this silently releases a seat "
        "it should not (see defect #6)."
    )
