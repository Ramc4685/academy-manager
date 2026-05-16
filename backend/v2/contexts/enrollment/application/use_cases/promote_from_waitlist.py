"""FIFO waitlist promotion.

Triggered by `Enrollment.EnrollmentCancelled` (admin cancel) or by admin
direct invocation. Picks the oldest waiting entry for the session and
transitions to `promoted`, emitting `WaitlistPromoted` for downstream
notification handlers.
"""

from __future__ import annotations

from backend.v2.contexts.enrollment.application.ports import WaitlistRepository
from backend.v2.contexts.enrollment.domain.events import (
    WaitlistPromoted,
    WaitlistPromotedPayload,
)
from backend.v2.shared.events import Outbox


class PromoteFromWaitlist:
    def __init__(
        self,
        *,
        waitlist: WaitlistRepository,
        outbox: Outbox,
        academy_id: str,
    ) -> None:
        self._waitlist = waitlist
        self._outbox = outbox
        self._academy_id = academy_id

    async def execute(self, session_id: str) -> str | None:
        """Returns the promoted entry's waitlist_id, or None if the list is empty."""
        entry = await self._waitlist.next_waiting(session_id)
        if entry is None:
            return None
        await self._waitlist.update_status(entry.waitlist_id, "promoted")
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
