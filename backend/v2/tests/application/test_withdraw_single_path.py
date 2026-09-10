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
    roster: RecordingRoster


def _build(status: str = "active") -> Harness:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment(status)})
    sessions = FakeSessions()
    outbox = FakeOutbox()
    events = FakeEnrollmentEvents()
    decision = FakeWithdrawalDecision()
    sync = RecordingBillingSync()
    roster = RecordingRoster()
    use_case = WithdrawEnrollment(
        enrollments=enrollments,
        enrollment_events=events,
        billing=decision,
        roster_notifier=roster,
        billing_sync=sync,
        sessions=sessions,
        outbox=outbox,
        clock=_now,
    )
    return Harness(use_case, enrollments, sessions, outbox, events, decision, sync, roster)


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
