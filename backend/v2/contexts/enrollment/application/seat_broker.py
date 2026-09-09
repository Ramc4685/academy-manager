"""SeatBroker — the single demand point for a seat (issue #697).

Demand for a seat is detected in exactly one place: a ``try_reserve_seat``
that returns ``False``. Every caller that needs a seat (roster add, resume,
transfer, waitlist promotion) routes through ``SeatBroker.acquire`` instead
of calling ``SessionWriter.try_reserve_seat`` directly, so reclaim-on-demand
is implemented once.

Imports only ports — no infrastructure (``lint-imports`` enforces this).

See the departures design contract §3 for the full algorithm and the
handover argument (§3.3) for why a successful reclaim performs NO seat
arithmetic: the victim leaves ``SEAT_HOLDING`` (-1 owed) and the requester
enters it (+1 owed) in the same instant, so leaving the counter alone is the
correct arithmetic, not a shortcut.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentBillingSync,
    EnrollmentDeparturePolicyLookup,
    EnrollmentEventRepository,
    HoldNotifier,
    HoldRepository,
    SessionWriter,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeatAcquisition:
    granted: bool
    via_reclaim: bool
    reclaimed_enrollment_id: str | None
    session_id: str
    #: Set only when via_reclaim — carried so a later ``release()`` can
    #: record the orphan event under the right tenant without a re-fetch.
    reclaimed_academy_id: str | None = None
    reclaimed_student_id: str | None = None


class SeatBroker:
    def __init__(
        self,
        *,
        sessions: SessionWriter,
        holds: HoldRepository,
        departure_policy: EnrollmentDeparturePolicyLookup,
        billing_sync: EnrollmentBillingSync | None = None,
        notifier: HoldNotifier | None = None,
        enrollment_events: EnrollmentEventRepository | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._holds = holds
        self._departure_policy = departure_policy
        self._billing_sync = billing_sync
        self._notifier = notifier
        self._enrollment_events = enrollment_events
        self._now = clock

    async def acquire(self, session_id: str, *, requested_by: str) -> SeatAcquisition:
        if await self._sessions.try_reserve_seat(session_id):
            return SeatAcquisition(
                granted=True, via_reclaim=False, reclaimed_enrollment_id=None, session_id=session_id
            )

        policy = await self._departure_policy.get_or_default()
        if getattr(policy, "hold_reclaim_policy", "never") != "longest_held":
            return SeatAcquisition(
                granted=False,
                via_reclaim=False,
                reclaimed_enrollment_id=None,
                session_id=session_id,
            )

        now = self._now()
        victim = await self._holds.claim_longest_held(
            session_id=session_id, now=now, requested_by=requested_by
        )
        if victim is None:
            return SeatAcquisition(
                granted=False,
                via_reclaim=False,
                reclaimed_enrollment_id=None,
                session_id=session_id,
            )

        # No release_seat, no second try_reserve_seat — the handover: the
        # victim's seat is transferred to the requester, net zero.
        await finalize_reclaim(
            victim,
            holds=self._holds,
            billing_sync=self._billing_sync,
            notifier=self._notifier,
            enrollment_events=self._enrollment_events,
            requested_by=requested_by,
            reason="reclaimed",
            seat_disposition="handed_over",
            sessions=self._sessions,
            now=now,
        )
        return SeatAcquisition(
            granted=True,
            via_reclaim=True,
            reclaimed_enrollment_id=victim.enrollment_id,
            session_id=session_id,
            reclaimed_academy_id=victim.academy_id,
            reclaimed_student_id=victim.student_id,
        )

    async def release(self, acquisition: SeatAcquisition) -> None:
        """Compensate a caller's own failed write AFTER a successful acquire.

        Always releases the seat — SI must hold regardless. When the seat
        came from a reclaim, the victim has already been dropped and
        emailed and CANNOT be un-dropped: this writes an audit event and
        logs a warning rather than pretending to undo anything.
        """
        await self._sessions.release_seat(acquisition.session_id)
        if acquisition.via_reclaim and acquisition.reclaimed_enrollment_id:
            log.warning(
                "hold_reclaim_orphaned",
                extra={
                    "session_id": acquisition.session_id,
                    "reclaimed_enrollment_id": acquisition.reclaimed_enrollment_id,
                },
            )
            if self._enrollment_events is not None:
                from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
                from backend.v2.shared.ids import new_ulid

                try:
                    await self._enrollment_events.record(
                        EnrollmentLifecycleEvent(
                            event_id=str(new_ulid()),
                            academy_id=acquisition.reclaimed_academy_id or "",
                            event_type="hold_reclaim_orphaned",
                            enrollment_id=acquisition.reclaimed_enrollment_id,
                            session_id=acquisition.session_id,
                            student_id=acquisition.reclaimed_student_id or "",
                            effective_at=self._now(),
                            occurred_at=self._now(),
                            metadata={
                                "reclaimed_enrollment_id": acquisition.reclaimed_enrollment_id
                            },
                        )
                    )
                except Exception:
                    log.exception("hold_reclaim_orphaned_event_failed")


async def finalize_reclaim(
    victim: Enrollment,
    *,
    holds: HoldRepository,
    sessions: SessionWriter | None,
    billing_sync: EnrollmentBillingSync | None,
    notifier: HoldNotifier | None,
    enrollment_events: EnrollmentEventRepository | None,
    requested_by: str | None,
    reason: Literal["reclaimed", "expired"],
    seat_disposition: Literal["handed_over", "release"],
    now: datetime,
) -> None:
    """Finish a claimed reclaim: withdraw the row, sync billing, notify.

    Non-defaulted ``seat_disposition`` so this can never be got wrong by
    omission: ``SeatBroker.acquire`` passes ``"handed_over"`` (no seat
    arithmetic — the seat is transferred, not freed); ``ExpireDueHolds`` and
    the stalled-reclaim sweep pass ``"release"`` (nobody is waiting).
    """
    finalized = await holds.finalize_reclaim(victim.enrollment_id, withdrawal_date=now)
    if finalized is None:
        # Already finalized by a concurrent caller (crash-recovery sweep vs.
        # the original acquire, say) — nothing left to do.
        return

    if seat_disposition == "release" and sessions is not None:
        await sessions.release_seat(victim.session_id)

    billing_result: str | None = None
    if billing_sync is not None:
        try:
            result = await billing_sync.apply(
                enrollment_id=victim.enrollment_id,
                transition="dropped",
                effective_at=now,
                reason=f"hold_{reason}",
                actor_id=None,
            )
            billing_result = str(result.get("billing_result")) if result else None
        except Exception:
            log.exception(
                "hold_reclaim_billing_sync_failed", extra={"enrollment_id": victim.enrollment_id}
            )
            billing_result = "billing_sync_failed"

    if enrollment_events is not None:
        from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
        from backend.v2.shared.ids import new_ulid

        try:
            await enrollment_events.record(
                EnrollmentLifecycleEvent(
                    event_id=str(new_ulid()),
                    academy_id=victim.academy_id,
                    event_type="hold_reclaimed" if reason == "reclaimed" else "hold_expired",
                    enrollment_id=victim.enrollment_id,
                    session_id=victim.session_id,
                    student_id=victim.student_id,
                    actor_id=None,
                    reason=f"hold_{reason}",
                    effective_at=now,
                    occurred_at=now,
                    billing_result=billing_result,
                    metadata={"requested_by": requested_by or ""},
                )
            )
        except Exception:
            log.exception("hold_reclaim_lifecycle_event_failed")

    if notifier is not None:
        try:
            await notifier.hold_reclaimed(
                enrollment_id=victim.enrollment_id,
                hold_seq=victim.hold_seq,
                session_id=victim.session_id,
                student_id=victim.student_id,
                hold_started_at=victim.hold_started_at or now,
                reason=reason,
                requested_by=requested_by,
                billing_result=billing_result,
            )
        except Exception:
            log.exception(
                "hold_reclaim_notify_failed", extra={"enrollment_id": victim.enrollment_id}
            )
