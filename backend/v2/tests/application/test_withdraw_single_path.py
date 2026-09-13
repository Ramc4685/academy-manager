"""Issue #670: one withdraw path, guarded both ways.

``WithdrawEnrollment`` is the only lifecycle writer; the credit decision is a
billing step it invokes. These tests pin the ordering and idempotency the
two old paths each got wrong: one credit, one seat release, future invoices
voided, one ``EnrollmentCancelled``, and a second call is a 409-class
domain error rather than a silent no-op or a double-decrement.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollment,
    CancelEnrollmentCommand,
    WithdrawEnrollment,
    WithdrawEnrollmentCommand,
)
from backend.v2.contexts.enrollment.domain.errors import (
    EnrollmentNotFound,
    EnrollmentNotWithdrawable,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentCancelled
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.application.test_enrollment_lifecycle_actions import (
    FakeEnrollmentEvents,
    FakeEnrollments,
    FakeOutbox,
    FakeSessions,
    FakeWithdrawalDecision,
    _enrollment,
    _now,
)
from backend.v2.tests.application.test_enrollment_lifecycle_billing_sync import (
    RecordingBillingSync,
    RecordingRoster,
)
from backend.v2.tests.fixtures.enrollment_fakes import (
    FakeHoldNotifier,
    FakeStudentsWithParent,
)
from backend.v2.tests.unit.test_roster_alert_adapter import (
    FakeSender as _AdapterSender,
)
from backend.v2.tests.unit.test_roster_alert_adapter import (
    FakeSessions as _AdapterSessions,
)
from backend.v2.tests.unit.test_roster_alert_adapter import (
    _adapter as _build_adapter,
)
from backend.v2.tests.unit.test_roster_alert_adapter import (
    _session as _adapter_session,
)
from backend.v2.tests.unit.test_roster_alert_adapter import (
    _staff as _adapter_staff,
)

EFFECTIVE = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _cmd(outcome: str = "credit") -> WithdrawEnrollmentCommand:
    return WithdrawEnrollmentCommand(
        enrollment_id="enr-1",
        effective_at=EFFECTIVE,
        outcome=outcome,  # type: ignore[arg-type]
        actor_id="owner-1",
        reason="moving away",
    )


@dataclass
class Harness:
    use_case: WithdrawEnrollment
    enrollments: FakeEnrollments
    sessions: FakeSessions
    outbox: FakeOutbox
    events: FakeEnrollmentEvents
    decision: FakeWithdrawalDecision
    sync: RecordingBillingSync
    #: RecordingRoster, or the real adapter when a test wires the send path.
    roster: Any
    notifier: FakeHoldNotifier


def _build(
    status: str = "active",
    *,
    notifier: FakeHoldNotifier | None = None,
    roster: Any | None = None,
) -> Harness:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment(status)})
    sessions = FakeSessions()
    outbox = FakeOutbox()
    events = FakeEnrollmentEvents()
    decision = FakeWithdrawalDecision()
    sync = RecordingBillingSync()
    roster = roster if roster is not None else RecordingRoster()
    notifier = notifier if notifier is not None else FakeHoldNotifier()
    use_case = WithdrawEnrollment(
        enrollments=enrollments,
        enrollment_events=events,
        billing=decision,
        roster_notifier=roster,
        billing_sync=sync,
        sessions=sessions,
        outbox=outbox,
        notifier=notifier,
        clock=_now,
    )
    return Harness(
        use_case, enrollments, sessions, outbox, events, decision, sync, roster, notifier
    )


@pytest.mark.asyncio
async def test_credit_withdraw_runs_every_side_effect_exactly_once() -> None:
    h = _build()

    await h.use_case.execute(_cmd("credit"))

    assert h.enrollments.rows["enr-1"].status == "dropped"
    # the credit decision ran once, for the CAS winner, with the admin's inputs
    assert [c["outcome"] for c in h.decision.calls] == ["credit"]
    assert h.decision.credits == {"enr-1": "credit-enr-1"}
    # the seat is released once
    assert h.sessions.reserved["sess-1"] == 0
    # billing followed: future invoices voided, autopay off
    assert [c["transition"] for c in h.sync.calls] == ["withdrawn"]
    assert h.sync.calls[0]["effective_at"] == EFFECTIVE
    # the event carries the credit and the sync result
    assert len(h.events.rows) == 1
    assert h.events.rows[0].event_type == "dropped"
    assert h.events.rows[0].billing_policy == "early_withdrawal_credit"
    assert h.events.rows[0].billing_result == "credit_approved;voided=1,autopay=disabled"
    assert h.events.rows[0].credit_id == "credit-enr-1"
    assert h.events.rows[0].metadata["outcome"] == "credit"
    # the seat is offered to the waitlist exactly once
    assert [type(e) for e in h.outbox.rows] == [EnrollmentCancelled]
    assert h.outbox.rows[0].payload.reason == "admin_cancel"
    # staff told last
    assert [c["change"] for c in h.roster.calls] == ["withdrawn"]


@pytest.mark.asyncio
async def test_second_withdraw_is_a_conflict_and_touches_nothing() -> None:
    h = _build()
    await h.use_case.execute(_cmd("credit"))

    with pytest.raises(EnrollmentNotWithdrawable) as excinfo:
        await h.use_case.execute(_cmd("refund"))

    assert excinfo.value.status_code == 409
    assert excinfo.value.details["status"] == "dropped"
    # nothing ran twice: no second decision, seat stays at 0, one event, one offer
    assert len(h.decision.calls) == 1
    assert h.sessions.reserved["sess-1"] == 0
    assert len(h.sync.calls) == 1
    assert len(h.events.rows) == 1
    assert len(h.outbox.rows) == 1
    assert len(h.roster.calls) == 1


@pytest.mark.asyncio
async def test_withdraw_after_cancel_is_a_conflict_not_a_second_seat_release() -> None:
    h = _build()
    await CancelEnrollment(
        enrollments=h.enrollments,
        sessions=h.sessions,
        outbox=h.outbox,
        academy_id="acad",
        enrollment_events=h.events,
        billing_sync=h.sync,
        clock=_now,
    ).execute(CancelEnrollmentCommand(enrollment_id="enr-1", actor_id="admin-1"))
    assert h.sessions.reserved["sess-1"] == 0

    with pytest.raises(EnrollmentNotWithdrawable):
        await h.use_case.execute(_cmd("credit"))

    assert h.decision.calls == []
    assert h.sessions.reserved["sess-1"] == 0
    assert h.enrollments.rows["enr-1"].status == "deleted"


@pytest.mark.asyncio
async def test_paused_row_withdraws_without_releasing_a_seat_it_no_longer_holds() -> None:
    h = _build("paused")
    # a paused row released its seat when it paused
    h.sessions.reserved["sess-1"] = 0

    await h.use_case.execute(_cmd("refund"))

    assert h.enrollments.rows["enr-1"].status == "dropped"
    assert h.sessions.reserved["sess-1"] == 0
    assert [c["transition"] for c in h.sync.calls] == ["withdrawn"]
    assert h.events.rows[0].billing_result == "refund_manual;voided=1,autopay=disabled"
    assert len(h.outbox.rows) == 1


@pytest.mark.asyncio
async def test_failed_credit_decision_still_withdraws_and_says_so() -> None:
    """The decision runs after the CAS, so it can no longer abandon a
    half-withdrawn row: the failure is recorded on the event instead."""
    h = _build()
    h.decision.fail = True

    await h.use_case.execute(_cmd("credit"))

    assert h.enrollments.rows["enr-1"].status == "dropped"
    assert h.sessions.reserved["sess-1"] == 0
    assert [c["transition"] for c in h.sync.calls] == ["withdrawn"]
    assert len(h.outbox.rows) == 1
    event = h.events.rows[0]
    assert event.billing_policy == "withdrawal_credit"
    assert event.billing_result.startswith("withdrawal_decision_failed")
    assert event.credit_id is None
    assert event.metadata["automation"] == "failed"


@pytest.mark.asyncio
async def test_lost_cas_race_is_a_conflict_and_issues_no_credit() -> None:
    """Two admins submit at once: both read `active`, only one CAS wins.

    The loser must not have written a credit — an APPROVED credit with no
    withdrawal event behind it is real money nobody can reconcile.
    """
    h = _build()
    original = h.enrollments.mark_withdrawn_if_open

    async def steal_then_flip(enrollment_id: str, *, withdrawal_date: datetime):
        # the other request lands between our read and our CAS
        await original(enrollment_id, withdrawal_date=withdrawal_date)
        return await original(enrollment_id, withdrawal_date=withdrawal_date)

    h.enrollments.mark_withdrawn_if_open = steal_then_flip  # type: ignore[method-assign]

    with pytest.raises(EnrollmentNotWithdrawable):
        await h.use_case.execute(_cmd("credit"))

    assert h.enrollments.rows["enr-1"].status == "dropped"
    # the loser released nothing, offered nothing and credited nothing
    assert h.sessions.reserved["sess-1"] == 1
    assert h.outbox.rows == []
    assert h.events.rows == []
    assert h.decision.calls == []
    assert h.decision.credits == {}


@pytest.mark.asyncio
async def test_two_concurrent_withdraws_issue_exactly_one_credit() -> None:
    """Both admins submit `credit` at the same moment. The CAS admits one, so
    only one of them ever reaches the credit ledger."""
    h = _build()
    results = await asyncio.gather(
        h.use_case.execute(_cmd("credit")),
        h.use_case.execute(_cmd("credit")),
        return_exceptions=True,
    )

    conflicts = [r for r in results if isinstance(r, EnrollmentNotWithdrawable)]
    assert len(conflicts) == 1, results
    assert h.enrollments.rows["enr-1"].status == "dropped"
    assert len(h.decision.calls) == 1
    assert h.decision.credits == {"enr-1": "credit-enr-1"}
    assert h.sessions.reserved["sess-1"] == 0
    assert len(h.events.rows) == 1
    assert len(h.outbox.rows) == 1


@pytest.mark.asyncio
async def test_missing_enrollment_is_not_found() -> None:
    h = _build()
    with pytest.raises(EnrollmentNotFound):
        await h.use_case.execute(_cmd().model_copy(update={"enrollment_id": "nope"}))


@pytest.mark.asyncio
async def test_withdraw_emails_the_family_when_dropped() -> None:
    """Issue #743: an admin-initiated Drop (or Stop all classes, which
    composes this use case) only reached the coach-facing roster notice —
    the family never learned their child was dropped."""
    h = _build()

    await h.use_case.execute(_cmd("credit"))

    [call] = h.notifier.dropped_calls
    assert call["enrollment_id"] == "enr-1"
    assert call["session_id"] == "sess-1"
    assert call["student_id"] == "stu-1"
    assert call["effective_at"] == EFFECTIVE
    assert call["reason"] == "moving away"


@pytest.mark.asyncio
async def test_withdraw_family_notify_failure_never_fails_the_drop() -> None:
    """Same best-effort contract as the roster notice and #740's hold-start
    notice: the drop is already committed, so a mail failure must not
    surface as a failed drop to the admin who performed it."""

    class _Exploding:
        async def enrollment_dropped(self, **_: object) -> None:
            raise RuntimeError("smtp down")

    h = _build(notifier=_Exploding())  # type: ignore[arg-type]

    await h.use_case.execute(_cmd("credit"))

    assert h.enrollments.rows["enr-1"].status == "dropped"


@pytest.mark.asyncio
async def test_withdraw_sends_the_family_exactly_one_email() -> None:
    """Issue #772: one Drop, one family email.

    Wired against the REAL roster-alert adapter, because the duplicate lived
    in its parent-copy routing and a recording port fake cannot see it: the
    staff alert and the family's drop notice both start from this one
    ``execute``.
    """
    sender = _AdapterSender()
    adapter = _build_adapter(
        sessions=_AdapterSessions(rows={"sess-1": _adapter_session()}),
        audiences=_adapter_staff(),
        sender=sender,
        students=FakeStudentsWithParent(),  # type: ignore[arg-type]
    )
    h = _build(roster=adapter)

    with tenant_scope("acad"):
        await h.use_case.execute(_cmd("credit"))

    # the family hears once, from the drop notice
    assert len(h.notifier.dropped_calls) == 1
    assert [row["user_id"] for row in sender.sent if row["user_id"] == "par-1"] == []
    # the coach/staff copy of the roster change is untouched (owner-1 made
    # the change, so they are the one staff member who is not mailed)
    assert [row["user_id"] for row in sender.sent] == ["coach-1", "admin-1"]
