"""The three-day waitlist confirmation window (issue #828).

A seat that frees up used to be handed to the next family the instant it
opened — an enrollment (and an invoice) for a class they may have long since
given up on. It is now OFFERED: the seat is held, the family has three days to
claim it, and an unanswered offer moves down the list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.application.use_cases.waitlist_offers import (
    ConfirmWaitlistOffer,
    SweepExpiredWaitlistOffers,
)
from backend.v2.contexts.enrollment.domain.errors import (
    WaitlistOfferExpired,
    WaitlistOfferNotFound,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry

ACADEMY = "acad"
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


@dataclass
class FakeWaitlist:
    entries: dict[str, WaitlistEntry] = field(default_factory=dict)

    async def next_waiting(self, session_id: str) -> WaitlistEntry | None:
        waiting = [
            e for e in self.entries.values() if e.session_id == session_id and e.status == "waiting"
        ]
        return sorted(waiting, key=lambda e: e.joined_at)[0] if waiting else None

    async def get(self, waitlist_id: str) -> WaitlistEntry | None:
        return self.entries.get(waitlist_id)

    async def update_status(self, waitlist_id: str, status: str) -> None:
        self.entries[waitlist_id] = self.entries[waitlist_id].model_copy(update={"status": status})

    async def mark_offered(self, waitlist_id: str, *, offer_expires_at: datetime) -> None:
        self.entries[waitlist_id] = self.entries[waitlist_id].model_copy(
            update={"status": "offered", "offer_expires_at": offer_expires_at}
        )

    async def find_expired_offers(self, *, before: datetime) -> list[WaitlistEntry]:
        return [
            e
            for e in self.entries.values()
            if e.status == "offered"
            and e.offer_expires_at is not None
            and e.offer_expires_at <= before
        ]


@dataclass
class FakeSessions:
    capacity: int = 1
    reserved: int = 0
    releases: list[str] = field(default_factory=list)

    async def get(self, session_id: str):
        return None

    async def try_reserve_seat(self, session_id: str) -> bool:
        if self.reserved >= self.capacity:
            return False
        self.reserved += 1
        return True

    async def release_seat(self, session_id: str) -> None:
        self.reserved -= 1
        self.releases.append(session_id)


@dataclass
class FakeEnrollments:
    rows: dict[str, Enrollment] = field(default_factory=dict)

    async def find_for_session_student(self, session_id: str, student_id: str):
        return next(
            (
                r
                for r in self.rows.values()
                if r.session_id == session_id and r.student_id == student_id
            ),
            None,
        )

    async def create(self, enrollment: Enrollment) -> None:
        self.rows[enrollment.enrollment_id] = enrollment

    async def update_status(self, enrollment_id: str, status: str) -> None:
        self.rows[enrollment_id] = self.rows[enrollment_id].model_copy(update={"status": status})


@dataclass
class FakeOutbox:
    events: list[object] = field(default_factory=list)

    async def append(self, event: object) -> None:
        self.events.append(event)


@dataclass
class FakeOfferNotifier:
    offered: list[dict[str, object]] = field(default_factory=list)
    expired: list[dict[str, object]] = field(default_factory=list)

    async def waitlist_offer_made(self, **kwargs: object) -> None:
        self.offered.append(kwargs)

    async def waitlist_offer_expired(self, **kwargs: object) -> None:
        self.expired.append(kwargs)


def _entry(waitlist_id: str, *, parent_id: str, student_id: str, days_ago: int) -> WaitlistEntry:
    return WaitlistEntry(
        waitlist_id=waitlist_id,
        academy_id=ACADEMY,
        session_id="sess-1",
        student_id=student_id,
        parent_id=parent_id,
        joined_at=NOW - timedelta(days=days_ago),
    )


def _promote(waitlist, sessions, enrollments, outbox, notifier, *, now=NOW):
    return PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions,
        enrollments=enrollments,
        outbox=outbox,
        academy_id=lambda: ACADEMY,
        offer_notifier=notifier,
        clock=lambda: now,
    )


def _confirm(waitlist, enrollments, outbox, *, now=NOW):
    return ConfirmWaitlistOffer(
        waitlist=waitlist,
        enrollments=enrollments,
        outbox=outbox,
        academy_id=lambda: ACADEMY,
        clock=lambda: now,
    )


@pytest.mark.asyncio
async def test_a_freed_seat_is_offered_and_held_not_seated() -> None:
    waitlist = FakeWaitlist(
        entries={"wl-1": _entry("wl-1", parent_id="par-1", student_id="stu-1", days_ago=10)}
    )
    sessions = FakeSessions()
    enrollments = FakeEnrollments()
    notifier = FakeOfferNotifier()

    result = await _promote(waitlist, sessions, enrollments, FakeOutbox(), notifier).execute(
        "sess-1"
    )

    assert result == "wl-1"
    assert waitlist.entries["wl-1"].status == "offered"
    assert waitlist.entries["wl-1"].offer_expires_at == NOW + timedelta(days=3)
    # The seat is HELD for the whole window — offering a seat that somebody
    # else can take in the meantime is not an offer.
    assert sessions.reserved == 1
    assert enrollments.rows == {}
    assert notifier.offered == [
        {
            "waitlist_id": "wl-1",
            "session_id": "sess-1",
            "student_id": "stu-1",
            "parent_user_id": "par-1",
            "offer_expires_at": NOW + timedelta(days=3),
        }
    ]


@pytest.mark.asyncio
async def test_confirming_an_offer_creates_the_enrollment_exactly_once() -> None:
    waitlist = FakeWaitlist(
        entries={"wl-1": _entry("wl-1", parent_id="par-1", student_id="stu-1", days_ago=10)}
    )
    sessions = FakeSessions()
    enrollments = FakeEnrollments()
    outbox = FakeOutbox()
    await _promote(waitlist, sessions, enrollments, outbox, FakeOfferNotifier()).execute("sess-1")

    confirm = _confirm(waitlist, enrollments, outbox, now=NOW + timedelta(days=1))
    enrollment_id = await confirm.execute("wl-1", parent_id="par-1")

    assert waitlist.entries["wl-1"].status == "promoted"
    assert enrollments.rows[enrollment_id].status == "active"
    assert len(enrollments.rows) == 1
    # The seat was already held by the offer: confirming must not reserve a
    # second one, which would put the class one over capacity.
    assert sessions.reserved == 1

    # A double click (or a retried request) is a no-op, not a second seat.
    again = await confirm.execute("wl-1", parent_id="par-1")
    assert again == enrollment_id
    assert len(enrollments.rows) == 1
    assert len([e for e in outbox.events if type(e).__name__ == "WaitlistPromoted"]) == 1


@pytest.mark.asyncio
async def test_another_familys_offer_reads_as_missing() -> None:
    waitlist = FakeWaitlist(
        entries={"wl-1": _entry("wl-1", parent_id="par-1", student_id="stu-1", days_ago=10)}
    )
    enrollments = FakeEnrollments()
    await _promote(
        waitlist, FakeSessions(), enrollments, FakeOutbox(), FakeOfferNotifier()
    ).execute("sess-1")

    with pytest.raises(WaitlistOfferNotFound):
        await _confirm(waitlist, enrollments, FakeOutbox()).execute("wl-1", parent_id="par-2")
    assert enrollments.rows == {}


@pytest.mark.asyncio
async def test_confirming_after_the_deadline_is_refused() -> None:
    waitlist = FakeWaitlist(
        entries={"wl-1": _entry("wl-1", parent_id="par-1", student_id="stu-1", days_ago=10)}
    )
    enrollments = FakeEnrollments()
    await _promote(
        waitlist, FakeSessions(), enrollments, FakeOutbox(), FakeOfferNotifier()
    ).execute("sess-1")

    late = _confirm(waitlist, enrollments, FakeOutbox(), now=NOW + timedelta(days=3, seconds=1))
    with pytest.raises(WaitlistOfferExpired):
        await late.execute("wl-1", parent_id="par-1")
    assert enrollments.rows == {}


@pytest.mark.asyncio
async def test_the_sweep_releases_an_unanswered_offer_and_offers_the_next_family() -> None:
    waitlist = FakeWaitlist(
        entries={
            "wl-1": _entry("wl-1", parent_id="par-1", student_id="stu-1", days_ago=10),
            "wl-2": _entry("wl-2", parent_id="par-2", student_id="stu-2", days_ago=5),
        }
    )
    sessions = FakeSessions()
    enrollments = FakeEnrollments()
    notifier = FakeOfferNotifier()
    await _promote(waitlist, sessions, enrollments, FakeOutbox(), notifier).execute("sess-1")
    assert waitlist.entries["wl-1"].status == "offered"

    after = NOW + timedelta(days=3, seconds=1)
    sweep = SweepExpiredWaitlistOffers(
        waitlist=waitlist,
        sessions=sessions,
        promote=_promote(waitlist, sessions, enrollments, FakeOutbox(), notifier, now=after),
        offer_notifier=notifier,
        clock=lambda: after,
    )
    result = await sweep.execute()

    assert result == {"expired": 1, "released": 1, "reoffered": 1}
    assert waitlist.entries["wl-1"].status == "expired"
    assert [c["waitlist_id"] for c in notifier.expired] == ["wl-1"]
    # The same single seat moved along the queue: still exactly one held.
    assert waitlist.entries["wl-2"].status == "offered"
    assert waitlist.entries["wl-2"].offer_expires_at == after + timedelta(days=3)
    assert sessions.reserved == 1
    assert enrollments.rows == {}
