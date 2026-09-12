"""Composition for departure policy + hold/return/reclaim (issue #697).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget (``test_composition_is_wiring`` is the check) — same reasoning as
``composition/billing_rules.py``. Attached onto the already-built
``AdminUseCases`` object in ``main.py`` (``AdminUseCases`` is a plain, non-
frozen dataclass; the mutation there mirrors how ``compose_admin_billing_rules``
extends ``app.state`` alongside ``compose_admin``'s own object).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.v2.contexts.enrollment.application.seat_broker import SeatBroker
from backend.v2.contexts.enrollment.application.use_cases.departure_policies import (
    GetEnrollmentDeparturePolicy,
    UpdateEnrollmentDeparturePolicy,
)
from backend.v2.contexts.enrollment.application.use_cases.holds import (
    ExpireDueHolds,
    HoldEnrollment,
    ProcessStalledReclaims,
    ReturnFromHold,
    SendHoldReminders,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_departure_policy_repo import (
    MongoDeparturePolicyRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_hold_repo import MongoHoldRepository
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter

if TYPE_CHECKING:
    from backend.v2.composition.hold_notifications import HoldNotificationAdapter


@dataclass
class EnrollmentHoldsComposition:
    departure_policy: GetEnrollmentDeparturePolicy
    update_departure_policy: UpdateEnrollmentDeparturePolicy
    hold_enrollment: HoldEnrollment
    return_from_hold: ReturnFromHold
    seat_broker: SeatBroker
    expire_due_holds: ExpireDueHolds
    process_stalled_reclaims: ProcessStalledReclaims
    send_hold_reminders: SendHoldReminders
    #: Issue #743: exposed so `main.py` can attach the same family-facing
    #: notifier onto `WithdrawEnrollment` post-hoc (that use case is
    #: composed separately in `composition/admin.py`, which is at its own
    #: wiring line-budget cap and has no `settings` in scope to build a
    #: second `compose_hold_notifications` instance).
    hold_notifier: HoldNotificationAdapter


def compose_enrollment_holds(db: Any, settings: Any) -> EnrollmentHoldsComposition:
    """Build every hold/departure-policy use case, including its own email
    and billing-sync adapters — a caller need only pass ``db``/``settings``,
    mirroring ``compose_enrollment_notifiers``. Kept out of
    ``composition/admin.py`` per that module's line-budget test; attach the
    result's fields onto the already-built ``AdminUseCases`` in ``main.py``.
    """
    from backend.v2.composition.hold_notifications import compose_hold_notifications
    from backend.v2.composition.lifecycle_billing import compose_enrollment_billing_sync
    from backend.v2.composition.roster_notifications import compose_roster_notifier
    from backend.v2.contexts.enrollment.infrastructure.mongo_billing_deferral_repo import (
        MongoBillingDeferralRepository,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_event_repo import (
        MongoEnrollmentEventRepository,
    )

    billing_sync = compose_enrollment_billing_sync(db)
    roster_notifier = compose_roster_notifier(db, settings)
    hold_notifier = compose_hold_notifications(db, settings)
    enrollment_events = MongoEnrollmentEventRepository(db)
    # Contract T1: a held month writes a BillingDeferral exactly like a
    # paused month does. Its own repo instance (composition/admin.py already
    # builds one, but this module cannot see it and is at its own line
    # budget for extra constructor plumbing) — same collection either way.
    billing_deferrals = MongoBillingDeferralRepository(db)

    policy_repo = MongoDeparturePolicyRepository(db)
    enrollments = MongoEnrollmentWriter(db)
    sessions = MongoSessionWriter(db)
    holds = MongoHoldRepository(db)

    hold_enrollment = HoldEnrollment(
        enrollments=enrollments,
        departure_policy=policy_repo,
        enrollment_events=enrollment_events,
        billing_sync=billing_sync,
        billing_deferrals=billing_deferrals,
        roster_notifier=roster_notifier,
        notifier=hold_notifier,
    )
    return_from_hold = ReturnFromHold(
        enrollments=enrollments,
        enrollment_events=enrollment_events,
        billing_sync=billing_sync,
        billing_deferrals=billing_deferrals,
        roster_notifier=roster_notifier,
        notifier=hold_notifier,
    )
    seat_broker = SeatBroker(
        sessions=sessions,
        holds=holds,
        departure_policy=policy_repo,
        billing_sync=billing_sync,
        notifier=hold_notifier,
        enrollment_events=enrollment_events,
    )
    expire_due_holds = ExpireDueHolds(
        holds=holds,
        sessions=sessions,
        departure_policy=policy_repo,
        billing_sync=billing_sync,
        notifier=hold_notifier,
        enrollment_events=enrollment_events,
    )
    process_stalled_reclaims = ProcessStalledReclaims(
        holds=holds,
        # A stalled row claimed by ExpireDueHolds (requested_by="hold_expiry")
        # must be finalized with seat_disposition="release", which needs the
        # sessions writer — see holds.py's ProcessStalledReclaims docstring.
        sessions=sessions,
        billing_sync=billing_sync,
        notifier=hold_notifier,
        enrollment_events=enrollment_events,
    )
    send_hold_reminders = SendHoldReminders(holds=holds, notifier=hold_notifier)

    return EnrollmentHoldsComposition(
        departure_policy=GetEnrollmentDeparturePolicy(policies=policy_repo),
        update_departure_policy=UpdateEnrollmentDeparturePolicy(policies=policy_repo),
        hold_enrollment=hold_enrollment,
        return_from_hold=return_from_hold,
        seat_broker=seat_broker,
        expire_due_holds=expire_due_holds,
        process_stalled_reclaims=process_stalled_reclaims,
        send_hold_reminders=send_hold_reminders,
        hold_notifier=hold_notifier,
    )
