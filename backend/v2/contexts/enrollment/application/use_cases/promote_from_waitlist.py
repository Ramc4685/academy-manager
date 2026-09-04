"""FIFO waitlist promotion.

Triggered by `Enrollment.EnrollmentCancelled` (admin cancel) or by admin
direct invocation. Picks the oldest waiting entry for the session and
transitions to `promoted`, emitting `WaitlistPromoted` for downstream
notification handlers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentEventRepository,
    EnrollmentWriter,
    RosterChangeNotifier,
    SessionWriter,
    WaitlistRepository,
)
from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded, SessionNotEnrollable
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentLifecycleEvent,
    WaitlistPromoted,
    WaitlistPromotedPayload,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


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
        self._now = clock

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
        else:
            reserved = await self._sessions.try_reserve_seat(entry.session_id)
            if not reserved:
                return None
            if existing is not None and existing.status == "paused":
                # Kept only for callers that wire no ``resume`` (issue #651).
                await self._enrollments.update_status(existing.enrollment_id, "active")
                enrollment = existing.model_copy(update={"status": "active"})
            else:
                enrollment = Enrollment(
                    enrollment_id=str(new_ulid()),
                    academy_id=academy_id,
                    session_id=entry.session_id,
                    student_id=entry.student_id,
                    status="active",
                )
                await self._enrollments.create(enrollment)

        await self._waitlist.update_status(entry.waitlist_id, "promoted")
        now = self._now()
        if self._enrollment_events is not None:
            await self._enrollment_events.record(
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
        await self._outbox.append(
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
        # #612: staff alert *and* the family's "a seat opened" email, both
        # behind one best-effort call. Last statement, after the seat, the
        # enrollment row and the waitlist status have all settled — and
        # swallowing, because a promotion that reports failure would be
        # re-run against a waitlist entry that is already `promoted`.
        # A resumed row already sent "resumed" from ResumeEnrollment (#651); a
        # second "a seat opened" email for the same event would be noise.
        if self._roster_notifier is not None and not resumed:
            try:
                await self._roster_notifier.roster_changed(
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
        return entry.waitlist_id
