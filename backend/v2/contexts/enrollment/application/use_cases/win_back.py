"""Win-back notices (issue #778).

Owner decision (2026-09-13 re-verification pass): automatic win-back
outreach at 30/60/90 days after a student's departure ("dropped" lifecycle
event), idempotent per ``(student, milestone)``, cancelled by re-enrollment.

Open owner question resolved to the safe default: a departed family that
still owes money is SUPPRESSED from win-back outreach entirely (not
deferred — the milestone is simply skipped and never retried once the
window has passed for it), so a dunning family never receives a
"come back" email in the same breath as an unpaid invoice. This is a
default, not a settled product decision; call it out in the release note.

Modeled directly on ``SendHoldReminders`` (``holds.py``): a same-shaped daily
job, same idempotent-claim pattern (``claim_digest_send`` via
``WinBackSendRepository``, mirroring ``MongoHoldNoticeSendRepository``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentEventRepository,
    EnrollmentQuery,
    StudentQuery,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent

log = logging.getLogger(__name__)

#: Milestones the owner asked for, in days-since-departure. Fixed set (not a
#: repeating step like the hold reminders' 30-day cadence) — a student who
#: has been gone 200 days is still only ever eligible for the 90-day notice.
WIN_BACK_MILESTONE_DAYS: tuple[int, ...] = (30, 60, 90)

#: How far back to look for "dropped" events on every tick. Must cover the
#: largest milestone plus slack for a late-running job, mirroring the
#: `send_hold_reminders` job's own tolerance for a missed day.
_LOOKBACK_DAYS = max(WIN_BACK_MILESTONE_DAYS) + 2


class WinBackSendRepository(Protocol):
    """Idempotent claim per ``(student_id, milestone_key, dropped_event_id)``
    — the same shape as ``MongoHoldNoticeSendRepository.try_claim``, wrapping
    ``claim_digest_send`` so a missed tick or a concurrent worker can never
    double-send a milestone. ``dropped_event_id`` scopes the claim to one
    departure cycle (review fix on #778): a student who drops, re-enrolls,
    and drops again must be eligible for a fresh 30/60/90 series, not
    permanently blocked by the first cycle's claims."""

    async def try_claim(
        self, *, academy_id: str, student_id: str, milestone_key: str, dropped_event_id: str
    ) -> dict[str, Any] | None: ...

    async def mark_sent(self, academy_id: str, send_id: str) -> None: ...


class FamilyBalanceLookup(Protocol):
    """Cross-context READ port (billing) — adapted in the composition root,
    never imported directly from ``contexts/enrollment`` (layering forbids
    a contexts→contexts import; see ``composition/win_back_send_repo.py``
    for the same reasoning applied to the send-claim repo)."""

    async def outstanding_cents_for_parent(self, parent_id: str) -> int: ...


class WinBackNotifier(Protocol):
    async def win_back(
        self,
        *,
        student_id: str,
        parent_id: str,
        milestone_days: int,
        dropped_at: datetime,
    ) -> None: ...


@dataclass(frozen=True)
class WinBackMilestoneRecord:
    """A row written for the timeline the same way `family_billing.py`
    persists an ``enrollment_events``-derived row for billing emails —
    win-back sends must satisfy that same "every lifecycle email persists a
    timeline row" bar."""

    student_id: str
    academy_id: str
    milestone_days: int
    dropped_event_id: str


class SendWinBackNotices:
    """Daily job: for every student who dropped 30/60/90 days ago and has
    not since re-enrolled and whose family does not currently owe money,
    send exactly one win-back notice per milestone (idempotent)."""

    def __init__(
        self,
        *,
        enrollment_events: EnrollmentEventRepository,
        enrollments: EnrollmentQuery,
        students: StudentQuery,
        send_repo: WinBackSendRepository,
        balance_lookup: FamilyBalanceLookup,
        notifier: WinBackNotifier | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollment_events = enrollment_events
        self._enrollments = enrollments
        self._students = students
        self._send_repo = send_repo
        self._balance_lookup = balance_lookup
        self._notifier = notifier
        self._now = clock

    async def execute(self, *, academy_id: str) -> int:
        if self._notifier is None:
            return 0
        now = self._now()
        window_start = now - timedelta(days=_LOOKBACK_DAYS)
        events = await self._enrollment_events.list_in_range(
            start=window_start,
            end=now,
            event_types=frozenset({"dropped"}),
        )
        sent = 0
        for event in events:
            sent += await self._process_event(event, now=now, academy_id=academy_id)
        return sent

    async def _process_event(
        self, event: EnrollmentLifecycleEvent, *, now: datetime, academy_id: str
    ) -> int:
        elapsed_days = (now - event.effective_at).days
        due_milestone = None
        for milestone in WIN_BACK_MILESTONE_DAYS:
            if elapsed_days >= milestone:
                due_milestone = milestone
        if due_milestone is None:
            return 0

        # Cancelled by re-enrollment: any currently active/held (SEAT_HOLDING)
        # enrollment for this student means the series is over — never
        # claim, never send, for ANY still-due milestone.
        current = await self._enrollments.seat_holding_for_student(event.student_id)
        if current:
            return 0

        students = await self._students.by_ids([event.student_id])
        student = students[0] if students else None
        if student is None:
            return 0

        # Owes-money suppression (owner's open question; default = suppress).
        outstanding = await self._balance_lookup.outstanding_cents_for_parent(student.parent_id)
        if outstanding > 0:
            return 0

        milestone_key = f"{due_milestone}"
        claim = await self._send_repo.try_claim(
            academy_id=academy_id,
            student_id=event.student_id,
            milestone_key=milestone_key,
            dropped_event_id=event.event_id,
        )
        if claim is None:
            return 0

        assert self._notifier is not None
        try:
            await self._notifier.win_back(
                student_id=event.student_id,
                parent_id=student.parent_id,
                milestone_days=due_milestone,
                dropped_at=event.effective_at,
            )
        except Exception:
            log.exception(
                "win_back_notice_failed",
                extra={"student_id": event.student_id, "milestone_days": due_milestone},
            )
            return 0

        await self._send_repo.mark_sent(academy_id, claim["send_id"])
        return 1
