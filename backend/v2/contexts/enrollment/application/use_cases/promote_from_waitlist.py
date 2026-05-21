"""FIFO waitlist promotion.

Triggered by `Enrollment.EnrollmentCancelled` (admin cancel) or by admin
direct invocation. Picks the oldest waiting entry for the session and
transitions to `promoted`, emitting `WaitlistPromoted` for downstream
notification handlers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentEventRepository,
    WaitlistRepository,
)
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentLifecycleEvent,
    WaitlistPromoted,
    WaitlistPromotedPayload,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.events import Outbox


Clock = Callable[[], datetime]


class PromoteFromWaitlist:
    def __init__(
        self,
        *,
        waitlist: WaitlistRepository,
        outbox: Outbox,
        academy_id: str,
        enrollment_events: EnrollmentEventRepository | None = None,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._waitlist = waitlist
        self._outbox = outbox
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._now = clock

    async def execute(
        self,
        session_id: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> str | None:
        """Returns the promoted entry's waitlist_id, or None if the list is empty."""
        entry = await self._waitlist.next_waiting(session_id)
        if entry is None:
            return None
        await self._waitlist.update_status(entry.waitlist_id, "promoted")
        now = self._now()
        if self._enrollment_events is not None:
            await self._enrollment_events.record(
                EnrollmentLifecycleEvent(
                    event_id=str(new_ulid()),
                    academy_id=self._academy_id,
                    event_type="promoted",
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
                academy_id=self._academy_id,
                payload=WaitlistPromotedPayload(
                    waitlist_id=entry.waitlist_id,
                    session_id=entry.session_id,
                    student_id=entry.student_id,
                    parent_id=entry.parent_id,
                ),
            )
        )
        return entry.waitlist_id
