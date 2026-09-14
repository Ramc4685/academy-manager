"""The two halves of the waitlist confirmation window (issue #828).

``PromoteFromWaitlist`` holds a freed seat and marks the entry ``offered``
with a deadline. Exactly one of these two use cases then closes the offer:

- :class:`ConfirmWaitlistOffer` — the family claimed it. The seat is ALREADY
  reserved (the offer is what holds it), so this creates the enrollment
  without touching the counter, then runs the shared promotion tail.
- :class:`SweepExpiredWaitlistOffers` — nobody answered. The held seat goes
  back, the entry is marked ``expired``, the family is told, and the next
  family on the list is offered the same seat.

Both are idempotent on the entry's status: confirming an already-``promoted``
offer returns the existing enrollment rather than creating a second one, and
the sweep only ever reads rows still marked ``offered``.
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
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
    record_promotion,
)
from backend.v2.contexts.enrollment.domain.errors import (
    WaitlistOfferExpired,
    WaitlistOfferNotFound,
    WaitlistOfferNotOpen,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


class ConfirmWaitlistOffer:
    """``offered`` -> ``promoted``: the family takes the seat being held."""

    def __init__(
        self,
        *,
        waitlist: WaitlistRepository,
        enrollments: EnrollmentWriter,
        outbox: Outbox,
        academy_id: Callable[[], str],
        enrollment_events: EnrollmentEventRepository | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._waitlist = waitlist
        self._enrollments = enrollments
        self._outbox = outbox
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._roster_notifier = roster_notifier
        self._now = clock

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
        if existing is not None and existing.status == "active":
            enrollment = existing
        elif existing is not None:
            await self._enrollments.update_status(existing.enrollment_id, "active")
            enrollment = existing.model_copy(update={"status": "active"})
        else:
            # No seat arithmetic: the offer has been holding this seat since
            # PromoteFromWaitlist reserved it.
            enrollment = Enrollment(
                enrollment_id=str(new_ulid()),
                academy_id=academy_id,
                session_id=entry.session_id,
                student_id=entry.student_id,
                status="active",
            )
            await self._enrollments.create(enrollment)

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
            await self._waitlist.update_status(entry.waitlist_id, "expired")
            try:
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
