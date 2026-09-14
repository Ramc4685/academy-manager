"""Wiring for the waitlist confirmation window (issue #828).

Its own module rather than more lines in ``composition/admin.py``, which is at
its documented line budget: the confirm use case is built by the parent BFF,
the sweep by the scheduler, and both want the same three repositories plus the
offer notifier, so one helper serves every caller.
"""

from __future__ import annotations

from typing import Any

from backend.v2.composition.roster_notifications import compose_roster_notifier
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.application.use_cases.waitlist_offers import (
    ConfirmWaitlistOffer,
    SweepExpiredWaitlistOffers,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_event_repo import (
    MongoEnrollmentEventRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter
from backend.v2.contexts.enrollment.infrastructure.mongo_waitlist_repo import (
    MongoWaitlistRepository,
)
from backend.v2.shared.events.outbox import MongoOutbox
from backend.v2.shared.tenancy import current_academy_id


def compose_confirm_waitlist_offer(db: Any, settings: Any) -> ConfirmWaitlistOffer:
    """The parent BFF's "yes, we want the seat"."""
    return ConfirmWaitlistOffer(
        waitlist=MongoWaitlistRepository(db),
        enrollments=MongoEnrollmentWriter(db),
        outbox=MongoOutbox(db),
        enrollment_events=MongoEnrollmentEventRepository(db),
        roster_notifier=compose_roster_notifier(db, settings),
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
