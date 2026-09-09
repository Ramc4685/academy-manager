"""Hold / Return / reclaim-recovery / reminder use cases (issue #697).

See the departures design contract §2-§4 for the full state machine. The
CAS-with-pre-image pattern here is the same one ``mark_withdrawn_if_open``
established: every transition returns ``Enrollment | None``, and ``None``
means the caller lost the race and MUST NOT touch seats, billing or email.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentBillingSync,
    EnrollmentDeparturePolicyLookup,
    EnrollmentEventRepository,
    EnrollmentWriter,
    HoldNotifier,
    HoldRepository,
    RosterChangeNotifier,
    SessionWriter,
)
from backend.v2.contexts.enrollment.application.seat_broker import finalize_reclaim
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.domain.departure_policy import (
    EnrollmentNotHoldable,
    EnrollmentNotReturnable,
    HoldWindowExceeded,
    compute_hold_expiry,
)
from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotFound
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]

#: Reminder cadence: 30-day steps on a daily job, NOT calendar months — see
#: contract §4.3. This keeps the cadence inside the day-denominated
#: max_hold_days cap unambiguously.
REMINDER_STEP_DAYS = 30

#: How long a reclaim_pending row may sit before a crash-recovery sweep
#: treats it as abandoned. Mirrors digest_claim.STALE_QUEUED_AFTER's
#: reasoning: comfortably above any job's own lease.
STALLED_RECLAIM_AFTER = timedelta(minutes=15)


async def _record_event(
    events: EnrollmentEventRepository | None,
    *,
    academy_id: str,
    event_type: str,
    enrollment_id: str,
    session_id: str,
    student_id: str,
    actor_id: str | None,
    reason: str | None,
    effective_at: datetime,
    occurred_at: datetime,
    billing_result: str | None = None,
) -> None:
    if events is None:
        return
    await events.record(
        EnrollmentLifecycleEvent(
            event_id=str(new_ulid()),
            academy_id=academy_id,
            event_type=event_type,
            enrollment_id=enrollment_id,
            session_id=session_id,
            student_id=student_id,
            actor_id=actor_id,
            reason=reason,
            effective_at=effective_at,
            occurred_at=occurred_at,
            billing_result=billing_result,
        )
    )


async def _sync_billing(
    billing_sync: EnrollmentBillingSync | None,
    *,
    enrollment_id: str,
    transition: str,
    effective_at: datetime,
    reason: str | None,
    actor_id: str | None,
) -> dict[str, object]:
    if billing_sync is None:
        log.error(
            "enrollment_billing_sync_unwired: %s for enrollment_id=%s", transition, enrollment_id
        )
        return {"billing_result": "billing_sync_unwired"}
    try:
        return await billing_sync.apply(
            enrollment_id=enrollment_id,
            transition=transition,
            effective_at=effective_at,
            reason=reason or "",
            actor_id=actor_id,
        )
    except Exception:
        log.exception("hold_billing_sync_failed", extra={"enrollment_id": enrollment_id})
        return {"billing_result": "billing_sync_failed"}


class HoldEnrollment:
    """active -> held. Keeps the seat. Requires a return date within the
    academy's configured max_hold_days."""

    def __init__(
        self,
        *,
        enrollments: EnrollmentWriter,
        departure_policy: EnrollmentDeparturePolicyLookup,
        enrollment_events: EnrollmentEventRepository | None = None,
        billing_sync: EnrollmentBillingSync | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._departure_policy = departure_policy
        self._enrollment_events = enrollment_events
        self._billing_sync = billing_sync
        self._roster_notifier = roster_notifier
        self._now = clock

    async def execute(
        self,
        enrollment_id: str,
        *,
        return_on: date,
        reason: str | None = None,
        actor_id: str | None = None,
    ) -> Enrollment:
        e = await self._enrollments.get(enrollment_id)
        if e is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=enrollment_id)
        if e.status == "paused":
            raise EnrollmentNotHoldable(
                "Resume this enrollment first, then place it on hold.",
                enrollment_id=enrollment_id,
                status=e.status,
            )
        if e.status != "active":
            raise EnrollmentNotHoldable(
                f"Only an active enrollment can be placed on hold (currently {e.status}).",
                enrollment_id=enrollment_id,
                status=e.status,
            )
        policy = await self._departure_policy.get_or_default()
        now = self._now()
        max_days = getattr(policy, "max_hold_days", 60)
        earliest = now.date()
        latest = earliest + timedelta(days=max_days)
        if return_on <= earliest or return_on > latest:
            raise HoldWindowExceeded(
                f"Return date must be after today and within {max_days} days.",
                enrollment_id=enrollment_id,
                return_on=return_on.isoformat(),
            )
        expires_at = compute_hold_expiry(now, max_days)
        before = await self._enrollments.mark_held_if_active(
            enrollment_id,
            started_at=now,
            return_on=return_on,
            expires_at=expires_at,
            reason=reason,
        )
        if before is None:
            raise EnrollmentNotHoldable(
                "Enrollment is no longer active; it cannot be placed on hold.",
                enrollment_id=enrollment_id,
                status=e.status,
            )
        billing = await _sync_billing(
            self._billing_sync,
            enrollment_id=enrollment_id,
            transition="held",
            effective_at=now,
            reason=reason,
            actor_id=actor_id,
        )
        await _record_event(
            self._enrollment_events,
            academy_id=e.academy_id,
            event_type="held",
            enrollment_id=enrollment_id,
            session_id=e.session_id,
            student_id=e.student_id,
            actor_id=actor_id,
            reason=reason,
            effective_at=now,
            occurred_at=now,
            billing_result=str(billing.get("billing_result")) if billing else None,
        )
        if self._roster_notifier is not None:
            try:
                await self._roster_notifier.roster_changed(
                    change="paused",
                    session_id=e.session_id,
                    student_id=e.student_id,
                    enrollment_id=enrollment_id,
                    actor_id=actor_id,
                )
            except Exception:
                log.exception("hold_roster_notify_failed")
        return e.model_copy(
            update={
                "status": "held",
                "hold_started_at": now,
                "hold_return_on": return_on,
                "hold_expires_at": expires_at,
                "hold_reason": reason,
                "hold_seq": e.hold_seq + 1,
            }
        )


class ReturnFromHold:
    """held -> active. MUST NOT reserve a seat — it was never released."""

    def __init__(
        self,
        *,
        enrollments: EnrollmentWriter,
        enrollment_events: EnrollmentEventRepository | None = None,
        billing_sync: EnrollmentBillingSync | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._enrollment_events = enrollment_events
        self._billing_sync = billing_sync
        self._roster_notifier = roster_notifier
        self._now = clock

    async def execute(
        self, enrollment_id: str, *, reason: str | None = None, actor_id: str | None = None
    ) -> Enrollment:
        e = await self._enrollments.get(enrollment_id)
        if e is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=enrollment_id)
        before = await self._enrollments.mark_active_if_held(enrollment_id)
        if before is None:
            raise EnrollmentNotReturnable(
                "Enrollment is not on hold (it may have been returned, reclaimed, or expired).",
                enrollment_id=enrollment_id,
                status=e.status,
            )
        now = self._now()
        billing = await _sync_billing(
            self._billing_sync,
            enrollment_id=enrollment_id,
            transition="returned",
            effective_at=now,
            reason=reason,
            actor_id=actor_id,
        )
        await _record_event(
            self._enrollment_events,
            academy_id=e.academy_id,
            event_type="returned",
            enrollment_id=enrollment_id,
            session_id=e.session_id,
            student_id=e.student_id,
            actor_id=actor_id,
            reason=reason,
            effective_at=now,
            occurred_at=now,
            billing_result=str(billing.get("billing_result")) if billing else None,
        )
        if self._roster_notifier is not None:
            try:
                await self._roster_notifier.roster_changed(
                    change="resumed",
                    session_id=e.session_id,
                    student_id=e.student_id,
                    enrollment_id=enrollment_id,
                    actor_id=actor_id,
                )
            except Exception:
                log.exception("return_roster_notify_failed")
        return before.model_copy(update={"status": "active"})


@dataclass
class ExpireDueHoldsResult:
    processed: int = 0
    expired: int = 0
    failed: int = 0


class ExpireDueHolds:
    """Daily sweep: drop every held row whose hold_expires_at has passed
    (contract §3.9 [DERIVED]). Uses seat_disposition="release" — nobody is
    waiting for this seat."""

    def __init__(
        self,
        *,
        holds: HoldRepository,
        sessions: SessionWriter,
        departure_policy: EnrollmentDeparturePolicyLookup,
        billing_sync: EnrollmentBillingSync | None = None,
        notifier: HoldNotifier | None = None,
        enrollment_events: EnrollmentEventRepository | None = None,
        scheduled_actions: ScheduledEnrollmentActionRepository | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._holds = holds
        self._sessions = sessions
        self._departure_policy = departure_policy
        self._billing_sync = billing_sync
        self._notifier = notifier
        self._enrollment_events = enrollment_events
        self._scheduled_actions = scheduled_actions
        self._now = clock

    async def execute(self) -> ExpireDueHoldsResult:
        now = self._now()
        result = ExpireDueHoldsResult()
        for row in await self._holds.list_expired(now=now):
            result.processed += 1
            # Claim THIS row by id — never the longest-held row on its
            # session. Expiry must drop the enrollment whose OWN
            # hold_expires_at has passed; claiming by session (as
            # `claim_longest_held` does) can silently pick a DIFFERENT,
            # unexpired hold on the same session and drop the wrong child.
            claimed = await self._holds.claim_expired(
                enrollment_id=row.enrollment_id, now=now, requested_by="hold_expiry"
            )
            if claimed is None:
                # Lost a race (Return, admin Drop, or a reclaim already
                # claimed this exact row) between list_expired and the claim
                # — nothing left to do for this row.
                continue
            try:
                await finalize_reclaim(
                    claimed,
                    holds=self._holds,
                    sessions=self._sessions,
                    billing_sync=self._billing_sync,
                    notifier=self._notifier,
                    enrollment_events=self._enrollment_events,
                    requested_by=None,
                    reason="expired",
                    seat_disposition="release",
                    now=now,
                )
                result.expired += 1
            except Exception:
                log.exception(
                    "hold_expiry_finalize_failed", extra={"enrollment_id": row.enrollment_id}
                )
                result.failed += 1
        return result


#: `requested_by` value `ExpireDueHolds.execute` claims with (see above,
#: `claim_expired(..., requested_by="hold_expiry")`). A stalled row carrying
#: this provenance was claimed by expiry, not by a SeatBroker reclaim — no
#: requester is waiting for its seat — and must be finalized the way expiry
#: would have, or the seat leaks and the family is emailed the wrong reason.
EXPIRY_REQUESTED_BY = "hold_expiry"


class ProcessStalledReclaims:
    """Crash recovery (contract §3.7): finish any reclaim_pending row whose
    claim is older than STALLED_RECLAIM_AFTER.

    Defaults to "handed_over" — the requester either completed its write
    (and holds the seat) or compensated via SeatBroker.release, which never
    re-releases here. The one exception is a row claimed by `ExpireDueHolds`
    (`hold_reclaim_for == "hold_expiry"`): nobody is waiting for that seat,
    so finalizing it as a reclaim would hand the seat to no one (leaking it,
    since "handed_over" performs no seat arithmetic) and email the family
    "reclaimed" instead of "expired". That row is finalized exactly as
    `ExpireDueHolds` itself would have: `seat_disposition="release"`,
    `reason="expired"`, `requested_by=None`.
    """

    def __init__(
        self,
        *,
        holds: HoldRepository,
        sessions: SessionWriter | None = None,
        billing_sync: EnrollmentBillingSync | None = None,
        notifier: HoldNotifier | None = None,
        enrollment_events: EnrollmentEventRepository | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._holds = holds
        self._sessions = sessions
        self._billing_sync = billing_sync
        self._notifier = notifier
        self._enrollment_events = enrollment_events
        self._now = clock

    async def execute(self) -> int:
        now = self._now()
        cutoff = now - STALLED_RECLAIM_AFTER
        finalized = 0
        for row in await self._holds.list_stalled(older_than=cutoff):
            if row.hold_reclaim_for == EXPIRY_REQUESTED_BY:
                requested_by: str | None = None
                reason: Literal["reclaimed", "expired"] = "expired"
                seat_disposition: Literal["handed_over", "release"] = "release"
                sessions = self._sessions
            else:
                requested_by = row.hold_reclaim_for
                reason = "reclaimed"
                seat_disposition = "handed_over"
                sessions = None
            await finalize_reclaim(
                row,
                holds=self._holds,
                sessions=sessions,
                billing_sync=self._billing_sync,
                notifier=self._notifier,
                enrollment_events=self._enrollment_events,
                requested_by=requested_by,
                reason=reason,
                seat_disposition=seat_disposition,
                now=now,
            )
            finalized += 1
        return finalized


class SendHoldReminders:
    """Daily job: send reminder N for every held row where it is due
    (contract §4.3). Only the highest-due N is sent per tick, so a job
    outage never produces a burst of back-dated reminders."""

    def __init__(
        self,
        *,
        holds: HoldRepository,
        notifier: HoldNotifier | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._holds = holds
        self._notifier = notifier
        self._now = clock

    async def execute(self) -> int:
        if self._notifier is None:
            return 0
        now = self._now()
        sent = 0
        for row in await self._holds.list_due_for_reminder():
            if row.hold_expires_at is not None and row.hold_expires_at <= now:
                continue
            if (
                row.hold_started_at is None
                or row.hold_return_on is None
                or row.hold_expires_at is None
            ):
                continue
            elapsed = now - row.hold_started_at
            n = int(elapsed.total_seconds() // (REMINDER_STEP_DAYS * 86400))
            if n < 1:
                continue
            due_at = row.hold_started_at + timedelta(days=n * REMINDER_STEP_DAYS)
            if due_at > row.hold_expires_at:
                continue
            try:
                await self._notifier.hold_reminder(
                    enrollment_id=row.enrollment_id,
                    hold_seq=row.hold_seq,
                    notice_index=n,
                    session_id=row.session_id,
                    student_id=row.student_id,
                    hold_started_at=row.hold_started_at,
                    hold_return_on=row.hold_return_on,
                    hold_expires_at=row.hold_expires_at,
                )
                sent += 1
            except Exception:
                log.exception("hold_reminder_failed", extra={"enrollment_id": row.enrollment_id})
        return sent
