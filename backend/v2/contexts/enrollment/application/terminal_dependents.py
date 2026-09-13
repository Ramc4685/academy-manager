"""What else has to close when an enrollment ends (issue #782).

An enrollment ending is never just a status write. Five other things believe
the row is live and have to be told:

* a pending ``cancel_at_period_end`` / ``resume_from_pause`` scheduled action,
  which would otherwise fire later against a row that is already history;
* the student's future one-time occurrence-roster rows (make-ups, trials),
  which would otherwise keep them on a coach's day sheet;
* an open billing deferral from the pause or hold the row ended in, which
  would otherwise sit in the admin warnings list forever;
* the ``EnrollmentCancelled`` event — the signal that offers the freed seat to
  the waitlist and expires a pending level-up recommendation;
* the staff roster alert.

``WithdrawEnrollment`` — the ONE withdraw path (#670) — did all of that
inline. ``seat_broker.finalize_reclaim``, which ends an enrollment just as
terminally when a hold is reclaimed, expired or orphaned, did none of it: it
wrote "dropped", synced billing and emailed the family, and every dependent
above went on behaving as though the child were still enrolled. That is the
"half-drop" of #782, and it is exactly the class of bug that a second
hand-written copy of a five-step bundle produces. So the bundle lives here,
once, and both paths call it.

Deliberately NOT in this bundle: the seat release and ``billing_sync``. Both
callers already own those and own them *differently* — a reclaim hands the
seat over with no arithmetic at all (contract §3.3) while a withdrawal
releases it only when the CAS pre-image was seat-holding, and the two sync
different transitions. Folding either in here would double-release a seat or
double-void an invoice, which is why this module takes them as already done.

Every step is best-effort: the status write that made the row terminal has
already committed, so a dependent that fails to close is recoverable, while
an exception propagating out of here would report a completed drop as failed
and send the caller into a retry that can only no-op.

Imports only ports — no infrastructure (``lint-imports`` enforces this), and
no use-case module either, so ``seat_broker`` can import it without the cycle
a helper left inside ``admin_writes`` would create.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from backend.v2.contexts.enrollment.application.ports import (
    OccurrenceRosterCleanup,
    RosterChangeKind,
    RosterChangeNotifier,
)
from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import (
    BillingDeferralRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentCancelled,
    EnrollmentCancelledPayload,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.events import Outbox

log = logging.getLogger(__name__)

#: Who freed the seat, in ``EnrollmentCancelledPayload.reason``'s closed
#: vocabulary (domain/events.py). Named here so a caller picks a value the
#: type checker can verify rather than a string that only fails at Pydantic
#: validation time, inside a best-effort block, in production.
EnrollmentCancelledReason = Literal["admin_cancel", "parent_cancel", "session_cancelled"]


@dataclass(frozen=True)
class TerminalDependents:
    """The ports :func:`close_terminal_enrollment_dependents` needs, as one
    value.

    Three separate reclaim entry points (``SeatBroker.acquire``,
    ``ExpireDueHolds``, ``ProcessStalledReclaims``) all end enrollments and all
    owe the same cleanup. Passing five optional ports through each of them
    separately is five chances to wire four — which is how the half-drop
    happened in the first place. One value, wired once in composition, either
    arrives whole or is ``None``.

    Every field is optional so a partially-wired composition (or a test) skips
    just that step.
    """

    scheduled_actions: ScheduledEnrollmentActionRepository | None = None
    occurrence_roster: OccurrenceRosterCleanup | None = None
    billing_deferrals: BillingDeferralRepository | None = None
    outbox: Outbox | None = None
    roster_notifier: RosterChangeNotifier | None = None


async def retire_scheduled_actions(
    scheduled_actions: ScheduledEnrollmentActionRepository | None,
    enrollment_id: str,
    *,
    reason: str,
) -> None:
    """Issue #675: an enrollment that just ended must not have a pending
    ``cancel_at_period_end`` (or ``resume_from_pause``) fire later against a
    row that is already cancelled / withdrawn. Best-effort — the status
    write has committed, and the processor's CAS refuses an ended row anyway;
    this keeps the blocked-actions list honest."""
    if scheduled_actions is None:
        return
    try:
        await scheduled_actions.cancel_pending_for_enrollment(enrollment_id, reason=reason)
    except Exception:
        log.exception(
            "enrollment.scheduled_action_retire_failed",
            extra={"enrollment_id": enrollment_id, "reason": reason},
        )


async def drop_future_occurrence_roster(
    cleanup: OccurrenceRosterCleanup | None,
    *,
    session_id: str,
    student_id: str,
    after: datetime,
) -> None:
    """Remove the student's future make-up/trial roster rows (issue #651).

    INVARIANT — every transition that stops attendance in a session (cancel,
    withdraw, session cancelled, hold reclaimed) calls this after the status
    write, so a coach's day sheet never lists a student whose enrollment is
    gone. Never raises: the enrollment write has already committed and a
    stale one-time row is recoverable, a cancel reported as failed is not.
    """
    if cleanup is None:
        return
    try:
        await cleanup.remove_future_for_student(
            session_id=session_id, student_id=student_id, after=after
        )
    except Exception:
        log.exception(
            "enrollment.occurrence_roster_cleanup_failed",
            extra={"session_id": session_id, "student_id": student_id},
        )


async def notify_roster_change(
    notifier: RosterChangeNotifier | None,
    *,
    change: RosterChangeKind,
    session_id: str,
    student_id: str,
    **details: object,
) -> None:
    """Fire a staff roster alert (#612) without ever risking the write.

    Every caller invokes this as the *last* statement of `execute`, after the
    state has settled: `CancelEnrollment` records its lifecycle event before
    `release_seat`, and the alert quotes a roster count, so firing earlier
    would announce a number that is about to change.

    Swallows everything. A notification failure that propagated would report a
    cancellation as failed to an admin whose cancellation actually happened —
    and the retry would then be a no-op against an already-cancelled row.
    """
    if notifier is None:
        return
    try:
        await notifier.roster_changed(
            change=change,
            session_id=session_id,
            student_id=student_id,
            **details,  # type: ignore[arg-type]
        )
    except Exception:
        log.exception(
            "enrollment.roster_notification_failed",
            extra={"change": change, "session_id": session_id, "student_id": student_id},
        )


async def close_billing_deferral(
    billing_deferrals: BillingDeferralRepository | None,
    enrollment_id: str,
    *,
    closed_at: datetime,
    closed_by: str,
    reason: str,
) -> None:
    """Close the pause/hold deferral the row ended inside (issue #782).

    A held month writes a ``BillingDeferral`` exactly like a paused month does
    (holds contract T1). When the row ends while still deferred, nothing ever
    closed it: the deferral stayed "active" and kept surfacing in the admin
    warnings list for a child who had left.
    """
    if billing_deferrals is None:
        return
    try:
        await billing_deferrals.close_active_for_enrollment(
            enrollment_id, closed_at=closed_at, closed_by=closed_by, reason=reason
        )
    except Exception:
        log.exception(
            "enrollment.billing_deferral_close_failed",
            extra={"enrollment_id": enrollment_id, "reason": reason},
        )


async def close_terminal_enrollment_dependents(
    enrollment: Enrollment,
    *,
    effective_at: datetime,
    reason: str,
    actor_id: str | None = None,
    roster_change: RosterChangeKind = "withdrawn",
    outbox_reason: EnrollmentCancelledReason = "admin_cancel",
    deferral_closed_by: str = "system",
    dependents: TerminalDependents | None = None,
) -> None:
    """Close everything that depended on this enrollment being live.

    Call it once, AFTER the status write that made the row terminal has
    committed and after the caller has settled the seat and billing sync it
    owns. ``dependents`` may be ``None`` (or carry ``None`` fields): an
    unwired port simply skips its step rather than failing.

    ``outbox_reason`` names who freed the seat, not how — the vocabulary is
    closed and has no hold-specific member. A reclaim keeps the default
    ``admin_cancel``: it IS an academy-side release, and which hold outcome
    caused it is already on the lifecycle event the caller wrote.
    """
    ports = dependents or TerminalDependents()
    await retire_scheduled_actions(ports.scheduled_actions, enrollment.enrollment_id, reason=reason)
    await drop_future_occurrence_roster(
        ports.occurrence_roster,
        session_id=enrollment.session_id,
        student_id=enrollment.student_id,
        after=effective_at,
    )
    await close_billing_deferral(
        ports.billing_deferrals,
        enrollment.enrollment_id,
        closed_at=effective_at,
        closed_by=actor_id or deferral_closed_by,
        reason=reason,
    )
    if ports.outbox is not None:
        # Emitted exactly once per terminal transition, by the caller that won
        # the status CAS — this is what offers the freed seat to the waitlist
        # and expires a pending level-up recommendation. A second emission
        # would promote two families into one seat.
        await ports.outbox.append(
            EnrollmentCancelled(
                aggregate_id=enrollment.enrollment_id,
                academy_id=enrollment.academy_id,
                payload=EnrollmentCancelledPayload(
                    enrollment_id=enrollment.enrollment_id,
                    session_id=enrollment.session_id,
                    student_id=enrollment.student_id,
                    reason=outbox_reason,
                ),
            )
        )
    await notify_roster_change(
        ports.roster_notifier,
        change=roster_change,
        session_id=enrollment.session_id,
        student_id=enrollment.student_id,
        enrollment_id=enrollment.enrollment_id,
        actor_id=actor_id,
    )
