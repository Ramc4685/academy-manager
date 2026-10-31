"""Issue #782 — a reclaimed hold is a terminal drop, so its dependents close.

``finalize_reclaim`` used to do four things: the CAS withdrawal, the optional
seat release, ``billing_sync.apply(transition="dropped")`` and the family
email. ``WithdrawEnrollment`` — the ONE withdraw path (#670) — does five more
for exactly the same terminal outcome: it retires pending scheduled actions,
drops the student's future one-time occurrence-roster rows, emits
``EnrollmentCancelled`` (which is what makes the waitlist promote somebody
into the freed seat and what expires a pending level-up) and tells staff.

So a hold that was reclaimed, expired or orphaned left the row reading
"dropped" while every dependent still behaved as if the child were enrolled:
a ``cancel_at_period_end`` still queued against a dead row, the child still on
next week's coach day sheet, nobody promoted off the waitlist into the seat,
and no staff alert. That is the "half-drop" of #782.

These tests drive ``finalize_reclaim`` directly with recording fakes so the
gap is visible without a broker or a hold repository in the way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.seat_broker import finalize_reclaim
from backend.v2.contexts.enrollment.application.terminal_dependents import TerminalDependents
from backend.v2.tests.fixtures.enrollment_fakes import (
    FakeBillingSync,
    FakeEnrollmentEvents,
    FakeEnrollmentWriter,
    FakeHoldNotifier,
    FakeHoldRepository,
    FakeSessionWriter,
    make_enrollment,
    make_session,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


@dataclass
class FakeScheduledActions:
    retired: list[tuple[str, str]] = field(default_factory=list)

    async def cancel_pending_for_enrollment(self, enrollment_id: str, *, reason: str) -> None:
        self.retired.append((enrollment_id, reason))


@dataclass
class FakeOccurrenceRoster:
    removed: list[dict[str, Any]] = field(default_factory=list)

    async def remove_future_for_student(
        self, *, session_id: str, student_id: str, after: datetime
    ) -> None:
        self.removed.append({"session_id": session_id, "student_id": student_id, "after": after})


@dataclass
class FakeOutbox:
    events: list[Any] = field(default_factory=list)

    async def append(self, event: Any, *, session: Any = None) -> None:
        self.events.append(event)

    async def pull_unprocessed(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    async def mark_processed(self, event_id: str) -> None:
        return None


@dataclass
class FakeRosterNotifier:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def roster_changed(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@dataclass
class FakeBillingDeferrals:
    closed: list[dict[str, Any]] = field(default_factory=list)

    async def close_active_for_enrollment(
        self, enrollment_id: str, *, closed_at: datetime, closed_by: str, reason: str
    ) -> None:
        self.closed.append(
            {
                "enrollment_id": enrollment_id,
                "closed_at": closed_at,
                "closed_by": closed_by,
                "reason": reason,
            }
        )


def _victim() -> Any:
    """The pre-image ``HoldRepository.claim_longest_held`` hands back: the row
    as it was (``held``) at the instant the CAS flipped it to
    ``reclaim_pending``. ``finalize_reclaim`` receives exactly this."""
    return make_enrollment("held-1", status="held", hold_started_at=NOW - timedelta(days=30))


def _claimed_store(victim: Any) -> FakeEnrollmentWriter:
    """The store as the CAS left it — the row already ``reclaim_pending``, so
    ``holds.finalize_reclaim`` inside the function under test can win it."""
    return FakeEnrollmentWriter(
        rows={victim.enrollment_id: victim.model_copy(update={"status": "reclaim_pending"})}
    )


@pytest.mark.asyncio
async def test_reclaimed_hold_closes_every_dependent_of_a_terminal_drop() -> None:
    victim = _victim()
    holds = FakeHoldRepository(enrollments=_claimed_store(victim))
    sessions = FakeSessionWriter(sessions={victim.session_id: make_session(capacity=4)})
    scheduled_actions = FakeScheduledActions()
    occurrence_roster = FakeOccurrenceRoster()
    outbox = FakeOutbox()
    roster_notifier = FakeRosterNotifier()
    billing_deferrals = FakeBillingDeferrals()

    await finalize_reclaim(
        victim,
        holds=holds,
        sessions=sessions,
        billing_sync=FakeBillingSync(),
        notifier=FakeHoldNotifier(),
        enrollment_events=FakeEnrollmentEvents(),
        requested_by="roster_add:new-student",
        reason="reclaimed",
        seat_disposition="handed_over",
        now=NOW,
        dependents=TerminalDependents(
            scheduled_actions=scheduled_actions,
            occurrence_roster=occurrence_roster,
            billing_deferrals=billing_deferrals,
            outbox=outbox,
            roster_notifier=roster_notifier,
        ),
    )

    # A pending cancel_at_period_end / resume_from_pause must not fire later
    # against a row that just ended.
    assert [row[0] for row in scheduled_actions.retired] == [victim.enrollment_id]
    # The child must leave next week's coach day sheet.
    assert occurrence_roster.removed == [
        {
            "session_id": victim.session_id,
            "student_id": victim.student_id,
            "after": NOW,
        }
    ]
    # The hold's billing deferral is closed — otherwise a dropped row keeps an
    # open deferral warning forever.
    assert [row["enrollment_id"] for row in billing_deferrals.closed] == [victim.enrollment_id]
    # EnrollmentCancelled is what promotes the waitlist and expires a pending
    # level-up. Without it every downstream handler believes the row is live.
    assert [type(event).__name__ for event in outbox.events] == ["EnrollmentCancelled"]
    payload = outbox.events[0].payload
    assert payload.enrollment_id == victim.enrollment_id
    assert payload.session_id == victim.session_id
    assert payload.student_id == victim.student_id
    # Staff hear about it, exactly as they do for an admin withdrawal.
    assert [call["change"] for call in roster_notifier.calls] == ["withdrawn"]


@pytest.mark.asyncio
async def test_dependent_cleanup_is_skipped_when_the_cas_was_already_finalized() -> None:
    """A concurrent finalizer already owns the drop — do not double-emit.

    ``EnrollmentCancelled`` offers the freed seat to the waitlist. Emitting it
    twice would promote two families into one seat, the failure the CAS exists
    to prevent, so the loser of the CAS must fall out before the bundle.
    """
    victim = _victim()
    holds = FakeHoldRepository(enrollments=_claimed_store(victim))
    # First call wins the CAS...
    await finalize_reclaim(
        victim,
        holds=holds,
        sessions=None,
        billing_sync=None,
        notifier=None,
        enrollment_events=None,
        requested_by="first",
        reason="reclaimed",
        seat_disposition="handed_over",
        now=NOW,
    )
    outbox = FakeOutbox()
    scheduled_actions = FakeScheduledActions()

    # ...the second finds nothing left to finalize.
    await finalize_reclaim(
        victim,
        holds=holds,
        sessions=None,
        billing_sync=None,
        notifier=None,
        enrollment_events=None,
        requested_by="second",
        reason="reclaimed",
        seat_disposition="handed_over",
        now=NOW,
        dependents=TerminalDependents(scheduled_actions=scheduled_actions, outbox=outbox),
    )

    assert outbox.events == []
    assert scheduled_actions.retired == []
