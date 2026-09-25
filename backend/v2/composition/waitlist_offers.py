"""Wiring for the waitlist confirmation window (issue #828).

Its own module rather than more lines in ``composition/admin.py``, which is at
its documented line budget: the confirm use case is built by the parent BFF,
the sweep by the scheduler, and both want the same three repositories plus the
offer notifier, so one helper serves every caller.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.v2.composition.roster_notifications import (
    compose_roster_notifier,
    format_session_schedule,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.application.use_cases.waitlist_offers import (
    ConfirmWaitlistOffer,
    DeclineWaitlistOffer,
    SweepExpiredWaitlistOffers,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_event_repo import (
    MongoEnrollmentEventRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_waitlist_repo import (
    MongoWaitlistRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.events.outbox import MongoOutbox
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time.mongo import ensure_utc


def compose_confirm_waitlist_offer(db: Any, settings: Any) -> ConfirmWaitlistOffer:
    """The parent BFF's "yes, we want the seat"."""
    return ConfirmWaitlistOffer(
        waitlist=MongoWaitlistRepository(db),
        enrollments=MongoEnrollmentWriter(db),
        outbox=MongoOutbox(db),
        enrollment_events=MongoEnrollmentEventRepository(db),
        roster_notifier=compose_roster_notifier(db, settings),
        # A seatless offer (X2) takes its seat at confirm; main.py attaches
        # the SeatBroker so that can reclaim a hold.
        sessions=MongoSessionWriter(db),
        # Request-time tenant, never the boot value (#532).
        academy_id=current_academy_id,
    )


def compose_sweep_expired_waitlist_offers(
    db: Any, settings: Any, *, promote: PromoteFromWaitlist
) -> SweepExpiredWaitlistOffers:
    """The hourly job that releases seats nobody claimed.

    ``promote`` is injected rather than built here on purpose: the admin
    container's instance is the one main.py has already attached the
    ``SeatBroker`` and ``ResumeEnrollment`` to, and the two structural guards
    (``test_seat_broker_wiring``, ``test_paused_promotion_resume_wiring``)
    exist precisely because a second, quietly-unwired construction is how
    #697 and #704 shipped.
    """
    return SweepExpiredWaitlistOffers(
        waitlist=MongoWaitlistRepository(db),
        sessions=MongoSessionWriter(db),
        promote=promote,
        offer_notifier=compose_roster_notifier(db, settings),
    )


def compose_decline_waitlist_offer(
    db: Any, *, promote: PromoteFromWaitlist
) -> DeclineWaitlistOffer:
    """The family's "no thanks", and staff withdrawing an offer.

    ``promote`` is the caller's own container instance for the same reason as
    the sweep: main.py attaches the ``SeatBroker`` to it after composition.
    """
    return DeclineWaitlistOffer(
        waitlist=MongoWaitlistRepository(db),
        sessions=MongoSessionWriter(db),
        promote=promote,
    )


#: How long a closed offer stays on the family's list. Long enough that a
#: parent clicking a stale email link sees what happened to it; short enough
#: that the list does not become a history page.
CLOSED_OFFER_VISIBLE_FOR = timedelta(days=14)

_PARENT_VISIBLE_STATUSES = frozenset({"waiting", "offered", "expired"})


def compose_list_parent_waitlist(
    db: Any,
) -> Callable[[str], Awaitable[list[dict[str, Any]]]]:
    """The parent's own waitlist rows: open offers first, with the deadline.

    ``expired`` rows are kept for ``CLOSED_OFFER_VISIBLE_FOR`` so a family
    that opens the offer email late is told the seat went to the next family
    instead of finding nothing at all.
    """
    waitlist = MongoWaitlistRepository(db)
    sessions = MongoSessionWriter(db)
    students = MongoStudentRepository(db)
    academies = MongoAcademyRepository(db)

    async def list_parent_waitlist(parent_id: str) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        entries = [
            e
            for e in await waitlist.list_for_parent(parent_id)
            if e.status in _PARENT_VISIBLE_STATUSES
            and not (
                e.status == "expired"
                and e.offer_expires_at is not None
                and e.offer_expires_at < now - CLOSED_OFFER_VISIBLE_FOR
            )
        ]
        if not entries:
            return []
        names = {
            s.student_id: s.full_name
            for s in await students.by_ids(sorted({e.student_id for e in entries}))
        }
        academy = await academies.find_by_id(current_academy_id()) or {}
        timezone = str(academy.get("timezone") or "") or None
        session_ids = sorted({e.session_id for e in entries})
        by_session = dict(
            zip(
                session_ids,
                await asyncio.gather(*(sessions.get(sid) for sid in session_ids)),
                strict=True,
            )
        )
        rows: list[dict[str, Any]] = []
        for entry in entries:
            session = by_session[entry.session_id]
            rows.append(
                {
                    "waitlist_id": entry.waitlist_id,
                    "session_id": entry.session_id,
                    "session_title": session.title if session else "Class",
                    "schedule_label": (
                        format_session_schedule(session, academy_timezone=timezone)
                        if session
                        else None
                    ),
                    "location": (session.location or None) if session else None,
                    "student_id": entry.student_id,
                    "student_name": names.get(entry.student_id) or "Your child",
                    "status": entry.status,
                    # Mongo hands back naive UTC (#706); say so on the wire.
                    "joined_at": ensure_utc(entry.joined_at),
                    "offer_expires_at": entry.offer_expires_at,
                }
            )
        order = {"offered": 0, "waiting": 1, "expired": 2}
        rows.sort(key=lambda r: order[r["status"]])
        return rows

    return list_parent_waitlist
