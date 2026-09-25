"""FIFO waitlist promotion — offer first, seat on confirmation (#828).

Triggered by `Enrollment.EnrollmentCancelled` (admin cancel) or by admin
direct invocation. Picks the oldest waiting entry for the session and, for a
family that needs a new enrollment, HOLDS the freed seat and marks the entry
`offered` with a three-day `offer_expires_at` instead of seating the child on
the spot. `ConfirmWaitlistOffer` turns an offer into the enrollment;
`SweepExpiredWaitlistOffers` releases an unanswered one and offers the seat to
the next family (both in `waitlist_offers.py`).

Two heads of the queue skip the window because no seat is being handed out to
a new family: an already-`active` row (nothing to claim) and a `paused` row,
which is the same enrollment coming back through `ResumeEnrollment`. Those go
straight to `promoted` via :func:`record_promotion`, which also emits
`WaitlistPromoted` for downstream notification handlers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

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
from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded, SessionNotEnrollable
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentLifecycleEvent,
    WaitlistPromoted,
    WaitlistPromotedPayload,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]

#: Issue #828 — how long a family has to claim a seat that opened for them.
#: The seat is held (reserved on the session) for the whole window, so this is
#: also how long the class runs one seat short when nobody answers.
DEFAULT_OFFER_WINDOW = timedelta(days=3)


async def record_promotion(
    entry: WaitlistEntry,
    enrollment: Enrollment,
    *,
    academy_id: str,
    waitlist: WaitlistRepository,
    outbox: Outbox,
    now: datetime,
    enrollment_events: EnrollmentEventRepository | None = None,
    roster_notifier: RosterChangeNotifier | None = None,
    actor_id: str | None = None,
    reason: str | None = None,
    notify_parent: bool = True,
) -> None:
    """Everything a promotion leaves behind once the seat is really taken.

    Shared by ``PromoteFromWaitlist`` (the paused/already-active head of the
    queue, which never goes through the offer window) and
    ``ConfirmWaitlistOffer`` (the family claiming an offered seat), so the
    lifecycle row, the ``WaitlistPromoted`` event and the staff/family alert
    are written in exactly one place rather than diverging between the two
    ways a seat gets taken (issue #828).
    """
    await waitlist.update_status(entry.waitlist_id, "promoted")
    if enrollment_events is not None:
        await enrollment_events.record(
            EnrollmentLifecycleEvent(
                event_id=str(new_ulid()),
                academy_id=academy_id,
                event_type="promoted",
                enrollment_id=enrollment.enrollment_id,
                waitlist_id=entry.waitlist_id,
                session_id=entry.session_id,
                student_id=entry.student_id,
                actor_id=actor_id,
                reason=reason,
                effective_at=now,
                occurred_at=now,
            )
        )
    await outbox.append(
        WaitlistPromoted(
            aggregate_id=entry.waitlist_id,
            academy_id=academy_id,
            payload=WaitlistPromotedPayload(
                waitlist_id=entry.waitlist_id,
                session_id=entry.session_id,
                student_id=entry.student_id,
                parent_id=entry.parent_id,
            ),
        )
    )
    # #612: staff alert *and* the family's "a seat opened" email, both behind
    # one best-effort call. Last statement, after the seat, the enrollment row
    # and the waitlist status have all settled — and swallowing, because a
    # promotion that reports failure would be re-run against a waitlist entry
    # that is already `promoted`. A resumed row already sent "resumed" from
    # ResumeEnrollment (#651); a second "a seat opened" email for the same
    # event would be noise.
    if roster_notifier is not None and notify_parent:
        try:
            await roster_notifier.roster_changed(
                change="promoted",
                session_id=entry.session_id,
                student_id=entry.student_id,
                enrollment_id=enrollment.enrollment_id,
                actor_id=actor_id,
                parent_user_id=entry.parent_id or None,
            )
        except Exception:
            log.exception(
                "enrollment.roster_notification_failed",
                extra={"change": "promoted", "session_id": entry.session_id},
            )


class PausedEnrollmentResumer(Protocol):
    """The ``ResumeEnrollment`` use case, by shape (issue #651).

    A paused student at the head of the waitlist is the same enrollment
    coming back, not a new one: seat reservation, waitlist cleanup, the
    lifecycle event, deferral close, autopay and billing sync, and the
    family's "resumed" email all live in ``ResumeEnrollment``. Routing the
    promotion through it keeps one code path (the way ``EditRosterAdd`` does)
    instead of an inline status flip that skipped all of that.
    """

    async def execute(
        self,
        enrollment_id: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> None: ...


class PromoteFromWaitlist:
    def __init__(
        self,
        *,
        waitlist: WaitlistRepository,
        sessions: SessionWriter,
        enrollments: EnrollmentWriter,
        outbox: Outbox,
        academy_id: Callable[[], str],
        enrollment_events: EnrollmentEventRepository | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        resume: PausedEnrollmentResumer | None = None,
        seat_broker: SeatBroker | None = None,
        offer_notifier: WaitlistOfferNotifier | None = None,
        offer_window: timedelta = DEFAULT_OFFER_WINDOW,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._waitlist = waitlist
        self._sessions = sessions
        self._enrollments = enrollments
        self._outbox = outbox
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._roster_notifier = roster_notifier
        self._resume = resume
        # Departures design contract §3.1 — optional so existing callers/
        # tests keep working unwired; production wiring injects this via
        # `set_seat_broker` from main.py (composition/admin.py is at its
        # line-budget cap, and SeatBroker is composed later).
        self._seat_broker = seat_broker
        self._offer_notifier = offer_notifier
        self._offer_window = offer_window
        self._now = clock

    def set_seat_broker(self, seat_broker: SeatBroker) -> None:
        self._seat_broker = seat_broker

    async def _release_quietly(self, session_id: str, acquisition: SeatAcquisition | None) -> None:
        """Give a just-acquired seat back without masking the error being handled.

        Mirrors ``EditRosterAdd._release_quietly`` (contract §3.8): when the
        seat came from ``SeatBroker.acquire`` (``acquisition`` is not
        ``None``), compensation MUST go through ``SeatBroker.release`` rather
        than a bare ``sessions.release_seat`` — a reclaim-granted acquisition
        already dropped and emailed a different family for this seat, and
        only the broker records that as a ``hold_reclaim_orphaned`` audit
        event rather than pretending nothing happened.
        """
        try:
            if self._seat_broker is not None and acquisition is not None:
                await self._seat_broker.release(acquisition)
            else:
                await self._sessions.release_seat(session_id)
        except Exception:  # pragma: no cover - defensive
            log.exception(
                "enrollment.waitlist_promotion_seat_release_failed",
                extra={"session_id": session_id},
            )

    async def execute(
        self,
        session_id: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> str | None:
        """Returns the promoted entry's waitlist_id, or None if the list is empty."""
        # Request-time tenant via the injected provider — never a boot-time value.
        academy_id = self._academy_id()
        # Issue #651: a cancelled class has no seats to hand out. CancelSession
        # emits one EnrollmentCancelled per row and each would otherwise
        # promote the next waiting family into a session that no longer runs.
        session = await self._sessions.get(session_id)
        if session is not None and session.status == "cancelled":
            log.info(
                "waitlist_promotion_skipped_session_cancelled",
                extra={"session_id": session_id},
            )
            return None
        # X2: an open seatless offer is first in line for a seat that frees
        # up. Otherwise the free seat would go to the next family while that
        # offer's confirm still reclaims a held family's seat.
        if await self._waitlist.count_seatless_offers(session_id):
            if await self._sessions.try_reserve_seat(session_id):
                upgraded = await self._waitlist.give_seat_to_seatless_offer(session_id)
                if upgraded is not None:
                    return upgraded.waitlist_id
                await self._release_quietly(session_id, None)
        entry = await self._waitlist.next_waiting(session_id)
        if entry is None:
            return None

        existing = await self._enrollments.find_for_session_student(
            entry.session_id, entry.student_id
        )
        resumed = False
        if existing is not None and existing.status == "active":
            enrollment = existing
        elif existing is not None and existing.status == "paused" and self._resume is not None:
            # Issue #651: same enrollment coming back — ResumeEnrollment owns
            # the seat reserve, the deferral/autopay/billing follow-through and
            # the family's "resumed" email. Full class => nothing promoted,
            # exactly as the inline reserve below reports it.
            try:
                await self._resume.execute(
                    existing.enrollment_id,
                    actor_id=actor_id,
                    reason=reason or "waitlist_promoted",
                )
            except (CapacityExceeded, SessionNotEnrollable):
                return None
            enrollment = existing.model_copy(update={"status": "active"})
            resumed = True
        elif existing is not None and existing.status == "paused":
            # Kept only for callers that wire no ``resume`` (#651). No offer
            # window either way: a paused child is a seat coming BACK to the
            # family that already had it, not one being handed to somebody new.
            acquisition, reserved = await self._reserve(entry)
            if not reserved:
                return None
            try:
                await self._enrollments.update_status(existing.enrollment_id, "active")
            except BaseException:
                await self._release_quietly(entry.session_id, acquisition)
                raise
            enrollment = existing.model_copy(update={"status": "active"})
        else:
            # Issue #828: a brand-new seat is OFFERED, not seated. The seat is
            # held for the confirmation window and the family claims it
            # through ``ConfirmWaitlistOffer``; ``SweepExpiredWaitlistOffers``
            # gives it to the next family if nobody answers.
            return await self._offer_seat(entry)

        now = self._now()
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
            reason=reason,
            notify_parent=not resumed,
        )
        return entry.waitlist_id

    async def _reserve(self, entry: WaitlistEntry) -> tuple[SeatAcquisition | None, bool]:
        """Take the freed seat, through the broker when one is wired."""
        if self._seat_broker is not None:
            acquisition = await self._seat_broker.acquire(
                entry.session_id, requested_by=f"waitlist_promotion:{entry.waitlist_id}"
            )
            return acquisition, acquisition.granted
        return None, await self._sessions.try_reserve_seat(entry.session_id)

    async def _can_offer_seatless(self, session_id: str) -> bool:
        """A seatless offer needs a hold it could reclaim on confirm — one per
        open seatless offer, so two families are never promised one hold."""
        if self._seat_broker is None:
            return False
        reclaimable = await self._seat_broker.reclaimable_seats(session_id)
        return reclaimable > await self._waitlist.count_seatless_offers(session_id)

    async def _offer_seat(self, entry: WaitlistEntry) -> str | None:
        """Offer the seat and give this family until the deadline (#828).

        A free seat is held for the window. A class full only of holds gets a
        seatless offer instead (X2): the hold is reclaimed on confirm, not now.
        Returns the entry's id once the offer is on the row, or ``None`` when
        no seat could be had — same "nothing promoted" answer the immediate
        path used to give a full class.
        """
        # X2 (owner decision 2026-09-25): an offer takes only a FREE seat. It
        # never goes through SeatBroker.acquire, because a reclaim there ends
        # a held family's enrollment for a family that has not said yes yet.
        # When the class is full only of holds the offer goes out seatless and
        # ConfirmWaitlistOffer reclaims at the moment the family confirms.
        holds_seat = await self._sessions.try_reserve_seat(entry.session_id)
        if not holds_seat and not await self._can_offer_seatless(entry.session_id):
            return None
        expires_at = self._now() + self._offer_window
        try:
            await self._waitlist.mark_offered(
                entry.waitlist_id, offer_expires_at=expires_at, holds_seat=holds_seat
            )
        except BaseException:
            if holds_seat:
                await self._release_quietly(entry.session_id, None)
            raise
        # Best-effort, and last: an offer the family never hears about is
        # recovered by the sweep (seat released, next family offered), while an
        # offer that reports failure would be re-made against an entry that is
        # already `offered` — a second held seat for the same family.
        if self._offer_notifier is not None and entry.parent_id:
            try:
                await self._offer_notifier.waitlist_offer_made(
                    waitlist_id=entry.waitlist_id,
                    session_id=entry.session_id,
                    student_id=entry.student_id,
                    parent_user_id=entry.parent_id,
                    offer_expires_at=expires_at,
                )
            except Exception:
                log.exception(
                    "enrollment.waitlist_offer_notification_failed",
                    extra={"waitlist_id": entry.waitlist_id, "session_id": entry.session_id},
                )
        return entry.waitlist_id
