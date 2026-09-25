"""X2: a waitlist OFFER never ends a held family's enrollment.

Reproduced 2026-09-25: under ``hold_reclaim_policy="longest_held"`` (the
default), promoting a waiting family into a class full only of holds went
through ``SeatBroker.acquire``, which dropped the longest-held family (and
emailed them) just to create an offer. Nothing could confirm that offer, so
three days later the sweep freed the seat and the held family was gone for
nothing.

Owner decision (2026-09-25): reclaim on confirm. The offer goes out
SEATLESS; the hold is reclaimed only when the waiting family says yes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.seat_broker import SeatBroker
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.application.use_cases.waitlist_offers import (
    ConfirmWaitlistOffer,
    DeclineWaitlistOffer,
    SweepExpiredWaitlistOffers,
)
from backend.v2.contexts.enrollment.domain.departure_policy import EnrollmentDeparturePolicy
from backend.v2.contexts.enrollment.domain.errors import WaitlistOfferSeatUnavailable
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.tests.application.test_waitlist_offers import FakeOutbox, FakeWaitlist
from backend.v2.tests.fixtures.enrollment_fakes import (
    FakeDeparturePolicyRepo,
    FakeEnrollmentEvents,
    FakeEnrollmentWriter,
    FakeHoldNotifier,
    FakeHoldRepository,
    FakeSessionWriter,
    make_enrollment,
    make_session,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class _Boom(Exception):
    pass


class _RaisingOnCreate(FakeEnrollmentWriter):
    async def create(self, enrollment) -> None:  # type: ignore[override]
        raise _Boom("create failed")


def _waiting(waitlist_id: str, *, parent: str, days_ago: int) -> WaitlistEntry:
    return WaitlistEntry(
        waitlist_id=waitlist_id,
        academy_id="acad",
        session_id="sess-1",
        student_id=f"stu-{waitlist_id}",
        parent_id=parent,
        joined_at=NOW - timedelta(days=days_ago),
    )


class _World:
    """One-seat class whose only seat is held; two families waiting."""

    def __init__(self, *, policy: str = "longest_held", enrollments=None) -> None:
        self.sessions = FakeSessionWriter(sessions={"sess-1": make_session("sess-1", capacity=1)})
        self.sessions.reserved_seats["sess-1"] = 1
        self.enrollments = enrollments or FakeEnrollmentWriter()
        self.enrollments.rows["held-1"] = make_enrollment(
            "held-1",
            session_id="sess-1",
            student_id="stu-held",
            status="held",
            hold_started_at=NOW - timedelta(days=9),
        )
        self.notifier = FakeHoldNotifier()
        self.events = FakeEnrollmentEvents()
        self.broker = SeatBroker(
            sessions=self.sessions,
            holds=FakeHoldRepository(enrollments=self.enrollments),
            departure_policy=FakeDeparturePolicyRepo(
                policy=EnrollmentDeparturePolicy(
                    academy_id="acad",
                    hold_reclaim_policy=policy,  # type: ignore[arg-type]
                )
            ),
            notifier=self.notifier,
            enrollment_events=self.events,
            clock=lambda: NOW,
        )
        self.waitlist = FakeWaitlist(
            entries={
                "wl-1": _waiting("wl-1", parent="p-1", days_ago=30),
                "wl-2": _waiting("wl-2", parent="p-2", days_ago=20),
            }
        )

    def promote(self, now: datetime = NOW) -> PromoteFromWaitlist:
        return PromoteFromWaitlist(
            waitlist=self.waitlist,
            sessions=self.sessions,
            enrollments=self.enrollments,
            outbox=FakeOutbox(),
            academy_id=lambda: "acad",
            seat_broker=self.broker,
            clock=lambda: now,
        )

    def confirm(self, now: datetime = NOW + timedelta(days=1)) -> ConfirmWaitlistOffer:
        return ConfirmWaitlistOffer(
            waitlist=self.waitlist,
            enrollments=self.enrollments,
            outbox=FakeOutbox(),
            academy_id=lambda: "acad",
            sessions=self.sessions,
            seat_broker=self.broker,
            clock=lambda: now,
        )


@pytest.mark.asyncio
async def test_an_offer_into_a_class_full_of_holds_is_seatless_and_drops_nobody() -> None:
    world = _World()

    assert await world.promote().execute("sess-1") == "wl-1"

    offer = world.waitlist.entries["wl-1"]
    assert offer.status == "offered"
    assert offer.offer_holds_seat is False
    assert world.enrollments.rows["held-1"].status == "held"
    assert world.notifier.reclaimed_calls == []
    assert world.events.rows == []
    assert world.sessions.reserved_seats["sess-1"] == 1


@pytest.mark.asyncio
async def test_one_hold_backs_at_most_one_seatless_offer() -> None:
    world = _World()
    await world.promote().execute("sess-1")

    # A second "Promote next" must not promise the same hold to a second family.
    assert await world.promote().execute("sess-1") is None
    assert world.waitlist.entries["wl-2"].status == "waiting"


@pytest.mark.asyncio
async def test_with_reclaim_off_a_class_full_of_holds_makes_no_offer() -> None:
    world = _World(policy="never")

    assert await world.promote().execute("sess-1") is None
    assert world.waitlist.entries["wl-1"].status == "waiting"


@pytest.mark.asyncio
async def test_a_free_seat_is_still_held_for_the_offer() -> None:
    world = _World()
    world.sessions.reserved_seats["sess-1"] = 0  # the held row's seat freed elsewhere

    await world.promote().execute("sess-1")

    assert world.waitlist.entries["wl-1"].offer_holds_seat is True
    assert world.sessions.reserved_seats["sess-1"] == 1
    assert world.enrollments.rows["held-1"].status == "held"


@pytest.mark.asyncio
async def test_confirming_a_seatless_offer_reclaims_the_hold_then() -> None:
    world = _World()
    await world.promote().execute("sess-1")

    enrollment_id = await world.confirm().execute("wl-1", parent_id="p-1")

    assert world.enrollments.rows["held-1"].status == "dropped"
    assert len(world.notifier.reclaimed_calls) == 1
    [event] = [e for e in world.events.rows if e.event_type == "hold_reclaimed"]
    assert event.metadata["requested_by"] == "waitlist_offer_confirm:wl-1"
    assert world.enrollments.rows[enrollment_id].status == "active"
    assert world.waitlist.entries["wl-1"].status == "promoted"
    assert world.sessions.reserved_seats["sess-1"] == 1  # handover, no arithmetic


@pytest.mark.asyncio
async def test_if_the_held_family_came_back_confirm_says_so_and_keeps_their_place() -> None:
    world = _World()
    await world.promote().execute("sess-1")
    # The held family returns before the waiting family answers.
    world.enrollments.rows["held-1"] = world.enrollments.rows["held-1"].model_copy(
        update={"status": "active"}
    )

    with pytest.raises(WaitlistOfferSeatUnavailable):
        await world.confirm().execute("wl-1", parent_id="p-1")

    assert world.waitlist.entries["wl-1"].status == "waiting"  # still first in line
    assert [r for r in world.enrollments.rows.values() if r.student_id == "stu-wl-1"] == []
    assert world.sessions.reserved_seats["sess-1"] == 1
    assert world.sessions.release_calls == []


@pytest.mark.asyncio
async def test_a_failed_enrollment_write_gives_the_reclaimed_seat_back() -> None:
    world = _World(enrollments=_RaisingOnCreate())
    await world.promote().execute("sess-1")

    with pytest.raises(_Boom):
        await world.confirm().execute("wl-1", parent_id="p-1")

    # The held family was already dropped and emailed and cannot be undone
    # (SeatBroker.release contract): the seat is released and the orphan is
    # recorded rather than hidden.
    assert world.sessions.release_calls == ["sess-1"]
    assert "hold_reclaim_orphaned" in [e.event_type for e in world.events.rows]


@pytest.mark.asyncio
async def test_an_unanswered_seatless_offer_expires_without_releasing_a_seat() -> None:
    world = _World()
    await world.promote().execute("sess-1")
    after = NOW + timedelta(days=3, seconds=1)

    result = await SweepExpiredWaitlistOffers(
        waitlist=world.waitlist,
        sessions=world.sessions,
        promote=world.promote(after),
        clock=lambda: after,
    ).execute()

    assert result["expired"] == 1
    assert world.sessions.release_calls == []
    assert world.sessions.reserved_seats["sess-1"] == 1
    assert world.enrollments.rows["held-1"].status == "held"
    # The next family gets the same (still seatless) chance.
    assert world.waitlist.entries["wl-2"].status == "offered"
    assert world.waitlist.entries["wl-2"].offer_holds_seat is False


@pytest.mark.asyncio
async def test_declining_a_seatless_offer_releases_nothing() -> None:
    world = _World()
    await world.promote().execute("sess-1")

    await DeclineWaitlistOffer(
        waitlist=world.waitlist,
        sessions=world.sessions,
        promote=world.promote(),
        clock=lambda: NOW,
    ).execute("wl-1", parent_id="p-1")

    assert world.waitlist.entries["wl-1"].status == "removed"
    assert world.sessions.release_calls == []
    assert world.sessions.reserved_seats["sess-1"] == 1
    assert world.enrollments.rows["held-1"].status == "held"
    assert world.waitlist.entries["wl-2"].status == "offered"
