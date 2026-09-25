"""The waitlist confirmation window (issue #828).

``PromoteFromWaitlist`` holds a freed seat and marks the entry ``offered``
with a deadline. Exactly one of these three use cases then closes the offer:

- :class:`ConfirmWaitlistOffer` — the family claimed it. The seat is ALREADY
  reserved (the offer is what holds it), so this creates the enrollment
  without touching the counter, then runs the shared promotion tail.
- :class:`SweepExpiredWaitlistOffers` — nobody answered. The held seat goes
  back, the entry is marked ``expired``, the family is told, and the next
  family on the list is offered the same seat.
- :class:`DeclineWaitlistOffer` — the family said no (or staff withdrew the
  offer). Same release-and-reoffer as the sweep, just without the wait.

All three key off the entry's status: confirming an already-``promoted``
offer returns the existing enrollment rather than creating a second one, and
the sweep and the decline close a row only by compare-and-set from
``offered``, so at most one of them ever releases its seat.

Scope: #828 was written with a second, unrelated half — the last-class,
pause-ending, first-class and level-up notices — and NONE of it is implemented
here or anywhere else in the tree. That half is carved out; see
``docs/tickets/enrollment-lifecycle-notices-828-followup.md``. #828 is not
satisfied by this module alone.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentEventRepository,
    EnrollmentWriter,
    RosterChangeNotifier,
    SessionWriter,
    WaitlistOfferNotifier,
    WaitlistRepository,
)
from backend.v2.contexts.enrollment.application.seat_broker import (
    SeatAcquisition,
    SeatBroker,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
    record_promotion,
)
from backend.v2.contexts.enrollment.domain.errors import (
    WaitlistOfferExpired,
    WaitlistOfferNotFound,
    WaitlistOfferNotOpen,
    WaitlistOfferSeatUnavailable,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


class ConfirmWaitlistOffer:
    """``offered`` -> ``promoted``: the family takes the seat being held.

    A seatless offer (X2) takes its seat here, through the ``SeatBroker``:
    this is the one moment a held family may lose their seat to a waitlist
    family, because this family has actually said yes.
    """

    def __init__(
        self,
        *,
        waitlist: WaitlistRepository,
        enrollments: EnrollmentWriter,
        outbox: Outbox,
        academy_id: Callable[[], str],
        enrollment_events: EnrollmentEventRepository | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        sessions: SessionWriter | None = None,
        seat_broker: SeatBroker | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._waitlist = waitlist
        self._enrollments = enrollments
        self._outbox = outbox
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._roster_notifier = roster_notifier
        self._sessions = sessions
        # Attached by main.py after composition, like every other seat taker.
        self._seat_broker = seat_broker
        self._now = clock

    def set_seat_broker(self, seat_broker: SeatBroker) -> None:
        self._seat_broker = seat_broker

    async def _take_seat(self, entry: WaitlistEntry) -> tuple[bool, SeatAcquisition | None]:
        """The seat a seatless offer never held. Reclaims a hold when the
        class is still full only of holds (policy permitting)."""
        if self._seat_broker is not None:
            acquisition = await self._seat_broker.acquire(
                entry.session_id, requested_by=f"waitlist_offer_confirm:{entry.waitlist_id}"
            )
            return acquisition.granted, acquisition
        if self._sessions is not None:
            return await self._sessions.try_reserve_seat(entry.session_id), None
        return False, None

    async def _give_seat_back(
        self, entry: WaitlistEntry, acquisition: SeatAcquisition | None
    ) -> None:
        try:
            if self._seat_broker is not None and acquisition is not None:
                await self._seat_broker.release(acquisition)
            elif self._sessions is not None:
                await self._sessions.release_seat(entry.session_id)
        except Exception:  # pragma: no cover - defensive
            log.exception(
                "enrollment.waitlist_confirm_seat_release_failed",
                extra={"waitlist_id": entry.waitlist_id},
            )

    async def execute(
        self,
        waitlist_id: str,
        *,
        parent_id: str | None = None,
        actor_id: str | None = None,
    ) -> str:
        """Returns the enrollment id. Confirming twice returns the same one."""
        entry = await self._waitlist.get(waitlist_id)
        # A stranger's entry reads exactly like a missing one: the id travels
        # in an email link, and a distinct 403 would confirm it exists.
        if entry is None or (parent_id is not None and entry.parent_id != parent_id):
            raise WaitlistOfferNotFound(f"No open waitlist offer {waitlist_id}")

        existing = await self._enrollments.find_for_session_student(
            entry.session_id, entry.student_id
        )
        if entry.status == "promoted":
            # Idempotent: a double-click, or a retried request whose first
            # attempt actually landed. The seat is already taken by this
            # family — creating a second enrollment would double-charge them
            # and double-count the roster.
            if existing is not None:
                return existing.enrollment_id
            raise WaitlistOfferNotOpen(f"Waitlist entry {waitlist_id} is already promoted")
        if entry.status == "expired":
            raise WaitlistOfferExpired(f"The offer on {waitlist_id} has expired")
        if entry.status != "offered":
            raise WaitlistOfferNotOpen(f"Waitlist entry {waitlist_id} is not an open offer")

        now = self._now()
        # The sweep may not have run yet; the deadline on the row is what
        # decides, so a late click is refused rather than quietly honoured.
        if entry.offer_expires_at is not None and entry.offer_expires_at <= now:
            raise WaitlistOfferExpired(f"The offer on {waitlist_id} has expired")

        academy_id = self._academy_id()
        # Claim the row first (compare-and-set). A decline, a staff withdraw or
        # the sweep closes an offer the same way and then releases its seat;
        # whoever loses must not go on to use that seat, or two families end
        # up on one place.
        if not await self._waitlist.transition_status(
            waitlist_id, expected="offered", to="promoted"
        ):
            current = await self._waitlist.get(waitlist_id)
            if current is not None and current.status == "promoted":
                again = await self._enrollments.find_for_session_student(
                    entry.session_id, entry.student_id
                )
                if again is not None:
                    return again.enrollment_id
            if current is not None and current.status == "expired":
                raise WaitlistOfferExpired(f"The offer on {waitlist_id} has expired")
            raise WaitlistOfferNotOpen(f"Waitlist entry {waitlist_id} is not an open offer")

        took_seat = False
        acquisition: SeatAcquisition | None = None
        if not entry.offer_holds_seat and not (
            existing is not None and existing.status == "active"
        ):
            took_seat, acquisition = await self._take_seat(entry)
            if not took_seat:
                # Nothing left to reclaim (the held family came back, or the
                # policy changed). Their place in the queue is kept: back to
                # waiting, still first by joined_at.
                await self._waitlist.transition_status(
                    waitlist_id, expected="promoted", to="waiting"
                )
                raise WaitlistOfferSeatUnavailable(
                    f"No seat is free for waitlist entry {waitlist_id} any more"
                )
        try:
            if existing is not None and existing.status == "active":
                enrollment = existing
            elif existing is not None:
                await self._enrollments.update_status(existing.enrollment_id, "active")
                enrollment = existing.model_copy(update={"status": "active"})
            else:
                # No further seat arithmetic: the offer held this seat since
                # PromoteFromWaitlist reserved it, or _take_seat just took it.
                enrollment = Enrollment(
                    enrollment_id=str(new_ulid()),
                    academy_id=academy_id,
                    session_id=entry.session_id,
                    student_id=entry.student_id,
                    status="active",
                )
                await self._enrollments.create(enrollment)
        except BaseException:
            if took_seat:
                await self._give_seat_back(entry, acquisition)
            # Reopen the offer: the family can try again before the deadline,
            # and the sweep still owns it after.
            await self._waitlist.transition_status(waitlist_id, expected="promoted", to="offered")
            raise

        await record_promotion(
            entry,
            enrollment,
            academy_id=academy_id,
            waitlist=self._waitlist,
            outbox=self._outbox,
            now=now,
            enrollment_events=self._enrollment_events,
            roster_notifier=self._roster_notifier,
            actor_id=actor_id,
            reason="waitlist_offer_confirmed",
        )
        return enrollment.enrollment_id


class SweepExpiredWaitlistOffers:
    """Hourly job: release seats nobody claimed and offer them onward."""

    def __init__(
        self,
        *,
        waitlist: WaitlistRepository,
        sessions: SessionWriter,
        promote: PromoteFromWaitlist,
        offer_notifier: WaitlistOfferNotifier | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._waitlist = waitlist
        self._sessions = sessions
        self._promote = promote
        self._offer_notifier = offer_notifier
        self._now = clock

    async def execute(self) -> dict[str, int]:
        now = self._now()
        expired = await self._waitlist.find_expired_offers(before=now)
        released = 0
        reoffered = 0
        for entry in expired:
            # Order matters: mark the row first. If the release then fails, the
            # reserved-seat reconciler recovers a seat; if the row were marked
            # last, a crash between the two would leave an `offered` row whose
            # seat is already gone, and the next sweep would release a seat
            # that belongs to somebody else.
            # Compare-and-set, not a blind write: a family that confirmed (or
            # declined) between the read above and here already owns this
            # row's seat, and releasing it would hand the seat out twice.
            if not await self._waitlist.transition_status(
                entry.waitlist_id, expected="offered", to="expired"
            ):
                continue
            try:
                # A seatless offer (X2) never took one; nothing to give back.
                if entry.offer_holds_seat:
                    await self._sessions.release_seat(entry.session_id)
            except Exception:
                log.exception(
                    "enrollment.waitlist_offer_seat_release_failed",
                    extra={"waitlist_id": entry.waitlist_id, "session_id": entry.session_id},
                )
                continue
            released += 1
            if self._offer_notifier is not None and entry.parent_id:
                try:
                    await self._offer_notifier.waitlist_offer_expired(
                        waitlist_id=entry.waitlist_id,
                        session_id=entry.session_id,
                        student_id=entry.student_id,
                        parent_user_id=entry.parent_id,
                    )
                except Exception:
                    log.exception(
                        "enrollment.waitlist_offer_expiry_notification_failed",
                        extra={"waitlist_id": entry.waitlist_id},
                    )
            # The seat is free again — hand it to the next family in line.
            # Never allowed to abort the sweep: one session's promotion
            # blowing up must not strand every other expired offer.
            try:
                if await self._promote.execute(entry.session_id) is not None:
                    reoffered += 1
            except Exception:
                log.exception(
                    "enrollment.waitlist_reoffer_failed",
                    extra={"session_id": entry.session_id},
                )
        return {"expired": len(expired), "released": released, "reoffered": reoffered}


class DeclineWaitlistOffer:
    """``offered`` -> ``removed`` (or ``skipped``): the held seat goes back now.

    Two callers. A family declining from the parent app passes ``parent_id``
    and gets the same not-found answer for a stranger's entry that confirm
    gives. Staff withdrawing an offer (the admin Remove/Skip on an ``offered``
    row) pass no ``parent_id``: before this existed, those buttons wrote a
    blind status over an ``offered`` row and the held seat was never released
    — the sweep only reads rows still marked ``offered``.
    """

    def __init__(
        self,
        *,
        waitlist: WaitlistRepository,
        sessions: SessionWriter,
        promote: PromoteFromWaitlist,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._waitlist = waitlist
        self._sessions = sessions
        self._promote = promote
        self._now = clock

    async def execute(
        self,
        waitlist_id: str,
        *,
        parent_id: str | None = None,
        outcome: str = "removed",
    ) -> bool:
        """``True`` when an open offer was closed and its seat released.

        For staff (no ``parent_id``) a row that is not an open offer returns
        ``False`` so the caller falls back to the plain skip/remove. For a
        family it raises the same errors confirm does.
        """
        entry = await self._waitlist.get(waitlist_id)
        if parent_id is None and (entry is None or entry.status != "offered"):
            return False
        if entry is None or (parent_id is not None and entry.parent_id != parent_id):
            raise WaitlistOfferNotFound(f"No open waitlist offer {waitlist_id}")
        if entry.status != "offered":
            if entry.status == "expired":
                raise WaitlistOfferExpired(f"The offer on {waitlist_id} has expired")
            raise WaitlistOfferNotOpen(f"Waitlist entry {waitlist_id} is not an open offer")
        if (
            parent_id is not None
            and entry.offer_expires_at is not None
            and entry.offer_expires_at <= self._now()
        ):
            # Past the deadline the seat belongs to the sweep; a decline now
            # would race it for the same release.
            raise WaitlistOfferExpired(f"The offer on {waitlist_id} has expired")

        if not await self._waitlist.transition_status(waitlist_id, expected="offered", to=outcome):
            # Lost to a confirm or the sweep between the read and the write.
            if parent_id is None:
                return False
            raise WaitlistOfferNotOpen(f"Waitlist entry {waitlist_id} is not an open offer")

        if entry.offer_holds_seat:
            try:
                await self._sessions.release_seat(entry.session_id)
            except Exception:
                # The decline has landed (the row is closed); a 500 now would
                # only make the family retry into a 409. The reserved-seat
                # reconciler recovers the counter.
                log.exception(
                    "enrollment.waitlist_decline_seat_release_failed",
                    extra={"session_id": entry.session_id, "waitlist_id": waitlist_id},
                )
                return True
        # Hand the seat to the next family. Best-effort: the decline itself
        # has landed, and a failed re-offer leaves a free seat the next
        # cancellation or the admin "Promote" button will fill.
        try:
            await self._promote.execute(entry.session_id)
        except Exception:
            log.exception(
                "enrollment.waitlist_reoffer_after_decline_failed",
                extra={"session_id": entry.session_id, "waitlist_id": waitlist_id},
            )
        return True
