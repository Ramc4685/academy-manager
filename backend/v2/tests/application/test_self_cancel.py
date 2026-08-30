"""Application/domain tests for parent self-cancel enrollment (R4).

Covers the pure ``compute_self_cancel_terms`` helper and the
``SelfCancelEnrollment`` use case: happy path, fee line via the (fake)
billing port, immediate vs end_of_period timing, ownership/status guards,
CAS double-submit protection, and preview/cancel parity.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotFound
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student
from backend.v2.contexts.enrollment.domain.self_service import (
    ParentSelfServicePolicy,
    SelfCancelTerms,
    compute_self_cancel_terms,
)

# ---------------------------------------------------------------------------
# Pure helper: compute_self_cancel_terms
# ---------------------------------------------------------------------------


def _policy(
    *,
    minimum_notice_days: int = 7,
    fee_cents: int = 2500,
    timing: str = "end_of_period",
) -> ParentSelfServicePolicy:
    return ParentSelfServicePolicy(
        academy_id="acad",
        cancellation_minimum_notice_days=minimum_notice_days,
        cancellation_fee_cents=fee_cents,
        cancellation_effective_timing=timing,  # type: ignore[arg-type]
    )


def test_notice_met_when_no_upcoming_occurrence() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    terms = compute_self_cancel_terms(_policy(), None, now)
    assert terms == SelfCancelTerms(notice_met=True, fee_cents=0)


def test_notice_met_at_exactly_the_boundary() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    next_start = now + timedelta(days=7)
    terms = compute_self_cancel_terms(_policy(minimum_notice_days=7), next_start, now)
    assert terms.notice_met is True
    assert terms.fee_cents == 0


def test_notice_not_met_inside_window_charges_fee() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    next_start = now + timedelta(days=3)
    terms = compute_self_cancel_terms(
        _policy(minimum_notice_days=7, fee_cents=2500), next_start, now
    )
    assert terms.notice_met is False
    assert terms.fee_cents == 2500


def test_fee_zero_when_policy_fee_zero_even_if_notice_not_met() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    next_start = now + timedelta(days=1)
    terms = compute_self_cancel_terms(_policy(minimum_notice_days=7, fee_cents=0), next_start, now)
    assert terms.notice_met is False
    assert terms.fee_cents == 0


# ---------------------------------------------------------------------------
# Use case: SelfCancelEnrollment (+ PreviewSelfCancel)
# ---------------------------------------------------------------------------

from backend.v2.contexts.enrollment.application.use_cases.self_cancel import (
    EnrollmentNotCancellable,
    PreviewSelfCancel,
    SelfCancelEnrollment,
    SelfCancelEnrollmentCommand,
)


def _enrollment(
    *,
    enrollment_id: str = "enr-1",
    student_id: str = "student-1",
    status: str = "active",
    session_id: str = "session-1",
) -> Enrollment:
    return Enrollment(
        enrollment_id=enrollment_id,
        academy_id="acad",
        session_id=session_id,
        student_id=student_id,
        status=status,  # type: ignore[arg-type]
    )


def _student(student_id: str = "student-1", parent_id: str = "parent-1") -> Student:
    return Student(student_id=student_id, academy_id="acad", parent_id=parent_id, full_name="Kid")


class _FakeOccurrenceForSession:
    """Fake next-upcoming-occurrence query, keyed by session_id."""

    def __init__(self, next_start_by_session: dict[str, datetime | None] | None = None) -> None:
        self._next_start_by_session = next_start_by_session or {}

    async def next_upcoming_start_for_session(
        self, session_id: str, *, now: datetime
    ) -> datetime | None:
        return self._next_start_by_session.get(session_id)


class _FakeStudents:
    def __init__(self, students: list[Student] | None = None) -> None:
        self._students = students or [_student()]

    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None:
        for s in self._students:
            if s.student_id == student_id and s.parent_id == parent_id:
                return s
        return None


class _FakePolicies:
    def __init__(self, policy: ParentSelfServicePolicy | None = None) -> None:
        self._policy = policy or _policy()

    async def get_or_default(self) -> ParentSelfServicePolicy:
        return self._policy


class _FakeEnrollments:
    """Fake enrollment writer supporting the CAS mark_cancelled_by_parent."""

    def __init__(self, enrollments: list[Enrollment] | None = None) -> None:
        self._by_id: dict[str, Enrollment] = {
            e.enrollment_id: e for e in (enrollments or [_enrollment()])
        }
        self.cancelled_calls: list[dict[str, Any]] = []
        self.fee_billing_error_calls: list[dict[str, Any]] = []

    async def get(self, enrollment_id: str) -> Enrollment | None:
        return self._by_id.get(enrollment_id)

    async def mark_cancelled_by_parent(
        self,
        enrollment_id: str,
        *,
        cancellation_reason: str,
        cancellation_policy_snapshot: dict[str, Any],
        cancelled_at: datetime,
    ) -> Enrollment | None:
        """Mirrors the atomic CAS mark_withdrawn-style writer method: only
        transitions when the enrollment is currently 'active'. Returns the
        updated Enrollment, or None if the CAS lost (not active anymore)."""
        current = self._by_id.get(enrollment_id)
        if current is None or current.status != "active":
            return None
        updated = current.model_copy(
            update={
                "status": "cancelled",
                "cancellation_policy_snapshot": cancellation_policy_snapshot,
            }
        )
        self._by_id[enrollment_id] = updated
        self.cancelled_calls.append(
            {
                "enrollment_id": enrollment_id,
                "cancellation_reason": cancellation_reason,
                "cancellation_policy_snapshot": cancellation_policy_snapshot,
                "cancelled_at": cancelled_at,
            }
        )
        return updated

    async def mark_fee_billing_error(self, enrollment_id: str, *, error: str) -> None:
        """Mirrors ``MongoEnrollmentWriter.mark_fee_billing_error``: a
        targeted, best-effort stamp of the failure onto the audit
        snapshot — used so the admin list can surface unrecovered
        fee-billing failures."""
        self.fee_billing_error_calls.append({"enrollment_id": enrollment_id, "error": error})
        current = self._by_id.get(enrollment_id)
        if current is None:
            return
        snapshot = dict(current.cancellation_policy_snapshot or {})
        snapshot["fee_billing_error"] = error
        self._by_id[enrollment_id] = current.model_copy(
            update={"cancellation_policy_snapshot": snapshot}
        )


class _FakeBilling:
    def __init__(self) -> None:
        self.fee_calls: list[dict[str, Any]] = []
        self._seen_idempotency_keys: set[str] = set()

    async def record_cancellation_fee(
        self,
        *,
        enrollment: Enrollment,
        fee_cents: int,
        reason: str,
        actor_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if idempotency_key in self._seen_idempotency_keys:
            return {"line_type": "fee", "amount_cents": fee_cents, "deduped": True}
        self._seen_idempotency_keys.add(idempotency_key)
        self.fee_calls.append(
            {
                "enrollment_id": enrollment.enrollment_id,
                "fee_cents": fee_cents,
                "reason": reason,
                "actor_id": actor_id,
                "idempotency_key": idempotency_key,
            }
        )
        return {"line_type": "fee", "amount_cents": fee_cents, "deduped": False}


class _FakeBillingThatFails:
    """Fake billing port that always raises, simulating a transient Mongo
    error or an ``AddInvoiceLine`` ``ValueError`` in the real adapter.

    ``error`` is a ``BaseException`` and not an ``Exception`` on purpose: the
    ordering tests below drive an ``asyncio.CancelledError`` through it, which
    the use case's ``except Exception`` around fee billing deliberately does
    NOT catch.
    """

    def __init__(
        self, error: BaseException | None = None, *, call_log: list[str] | None = None
    ) -> None:
        self.error = error or RuntimeError("mongo write timed out")
        self.calls = 0
        self._call_log = call_log if call_log is not None else []

    async def record_cancellation_fee(
        self,
        *,
        enrollment: Enrollment,
        fee_cents: int,
        reason: str,
        actor_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.calls += 1
        self._call_log.append("record_cancellation_fee")
        raise self.error


class _FakeSessions:
    """Fake ``SelfCancelSessionWriter``: records every seat release so tests
    can assert the reserved-seat counter is decremented exactly once."""

    def __init__(self, *, call_log: list[str] | None = None) -> None:
        self.released: list[str] = []
        self._call_log = call_log if call_log is not None else []

    async def release_seat(self, session_id: str) -> None:
        self._call_log.append("release_seat")
        self.released.append(session_id)


class _FakeSessionsThatFail:
    """Seat release that always raises — the deliberate 500-on-committed-cancel
    trade-off documented in the module's ERROR HANDLING section."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or RuntimeError("mongo write timed out")
        self.calls = 0

    async def release_seat(self, session_id: str) -> None:
        self.calls += 1
        raise self.error


class _FakeOutbox:
    def __init__(self, *, call_log: list[str] | None = None) -> None:
        self.events: list[Any] = []
        self._call_log = call_log if call_log is not None else []

    async def append(self, event: Any, *, session: Any = None) -> None:
        self._call_log.append("outbox_append")
        self.events.append(event)


class _FakeLifecycleEvents:
    """Fake ``SelfCancelLifecycleEventRecorder``: the admin enrollment
    timeline. Without a row here the timeline shows the waitlist ``promoted``
    event with nothing explaining the seat that freed up."""

    def __init__(self, *, call_log: list[str] | None = None) -> None:
        self.recorded: list[Any] = []
        self._call_log = call_log if call_log is not None else []

    async def record(self, event: Any) -> None:
        self._call_log.append("lifecycle_record")
        self.recorded.append(event)


def _use_case(
    *,
    enrollments: _FakeEnrollments | None = None,
    students: _FakeStudents | None = None,
    policies: _FakePolicies | None = None,
    occurrences: _FakeOccurrenceForSession | None = None,
    billing: _FakeBilling | None = None,
    sessions: _FakeSessions | None = None,
    outbox: _FakeOutbox | None = None,
    enrollment_events: _FakeLifecycleEvents | None = None,
    clock=lambda: datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
) -> SelfCancelEnrollment:
    return SelfCancelEnrollment(
        enrollments=enrollments or _FakeEnrollments(),
        students=students or _FakeStudents(),
        policies=policies or _FakePolicies(),
        occurrences=occurrences or _FakeOccurrenceForSession(),
        sessions=sessions or _FakeSessions(),
        outbox=outbox or _FakeOutbox(),
        billing=billing,
        enrollment_events=enrollment_events,
        clock=clock,
    )


async def test_happy_path_sufficient_notice_no_fee_audit_fields_set() -> None:
    enrollments = _FakeEnrollments([_enrollment()])
    billing = _FakeBilling()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=2500, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=30)}),
        billing=billing,
        clock=lambda: now,
    )

    result = await uc.execute(
        SelfCancelEnrollmentCommand(
            enrollment_id="enr-1", parent_id="parent-1", reason="moving away"
        )
    )

    assert result.fee_cents == 0
    assert result.status == "cancelled"
    assert not billing.fee_calls

    [call] = enrollments.cancelled_calls
    assert call["cancellation_reason"] == "moving away"
    snapshot = call["cancellation_policy_snapshot"]
    assert snapshot["cancellation_minimum_notice_days"] == 7
    assert snapshot["cancellation_fee_cents"] == 2500
    assert snapshot["cancellation_effective_timing"] == "immediate"
    assert snapshot["fee_cents"] == 0
    assert snapshot["notice_met"] is True
    assert call["cancelled_at"] == now


async def test_insufficient_notice_appends_fee_line_via_billing_port() -> None:
    enrollments = _FakeEnrollments([_enrollment()])
    billing = _FakeBilling()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=2500, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=2)}),
        billing=billing,
        clock=lambda: now,
    )

    result = await uc.execute(
        SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="too far")
    )

    assert result.fee_cents == 2500
    [fee_call] = billing.fee_calls
    assert fee_call["fee_cents"] == 2500
    assert fee_call["idempotency_key"] == "enr-1-self-cancel-fee"


async def test_fee_billing_failure_still_returns_success_and_stamps_admin_visible_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reviewer finding: the CAS commits the cancellation first, so a
    subsequent billing-port failure (transient Mongo error, AddInvoiceLine
    ValueError, etc.) must never propagate as an opaque 500. execute()
    still returns success, the enrollment stays cancelled, a structured
    warning is logged, and the failure is stamped onto the audit snapshot
    so ListSelfCancellationsForAdmin can surface it (project rule: "Admin
    must see unrecovered failures")."""
    enrollments = _FakeEnrollments([_enrollment()])
    billing = _FakeBillingThatFails(RuntimeError("mongo write timed out"))
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=2500, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=2)}),
        billing=billing,
        clock=lambda: now,
    )

    with caplog.at_level("WARNING"):
        result = await uc.execute(
            SelfCancelEnrollmentCommand(
                enrollment_id="enr-1", parent_id="parent-1", reason="too far"
            )
        )

    # 1. execute() still returns success — the CAS is the source of truth.
    assert result.status == "cancelled"
    assert result.fee_cents == 2500
    assert billing.calls == 1

    # 2. Enrollment itself ends cancelled (not rolled back).
    persisted = await enrollments.get("enr-1")
    assert persisted is not None
    assert persisted.status == "cancelled"

    # 3. The failure is stamped into the audit snapshot for admin visibility.
    [stamp_call] = enrollments.fee_billing_error_calls
    assert stamp_call["enrollment_id"] == "enr-1"
    assert "mongo write timed out" in stamp_call["error"]
    assert persisted.cancellation_policy_snapshot is not None
    assert "mongo write timed out" in persisted.cancellation_policy_snapshot["fee_billing_error"]

    # 4. A structured log record is emitted.
    matching = [r for r in caplog.records if r.message == "self_cancel_fee_billing_failed"]
    assert len(matching) == 1
    record = matching[0]
    assert record.enrollment_id == "enr-1"  # type: ignore[attr-defined]
    assert record.fee_cents == 2500  # type: ignore[attr-defined]
    assert "mongo write timed out" in record.error  # type: ignore[attr-defined]


async def test_immediate_timing_sets_cancelled_at_now() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    enrollments = _FakeEnrollments([_enrollment()])
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": None}),
        clock=lambda: now,
    )

    result = await uc.execute(
        SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="r")
    )

    assert result.effective_timing == "immediate"
    assert result.cancelled_at == now


async def test_end_of_period_timing_sets_cancelled_at_end_of_month() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    enrollments = _FakeEnrollments([_enrollment()])
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(timing="end_of_period")),
        occurrences=_FakeOccurrenceForSession({"session-1": None}),
        clock=lambda: now,
    )

    result = await uc.execute(
        SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="r")
    )

    assert result.effective_timing == "end_of_period"
    assert result.cancelled_at == datetime(2026, 7, 31, 23, 59, 59, 999999, tzinfo=UTC)
    assert result.status == "cancelled"


async def test_wrong_parent_raises_enrollment_not_found() -> None:
    enrollments = _FakeEnrollments([_enrollment()])
    uc = _use_case(
        enrollments=enrollments, students=_FakeStudents([_student(parent_id="parent-1")])
    )

    with pytest.raises(EnrollmentNotFound):
        await uc.execute(
            SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="someone-else", reason="r")
        )


async def test_non_active_enrollment_raises_not_cancellable() -> None:
    enrollments = _FakeEnrollments([_enrollment(status="paused")])
    uc = _use_case(enrollments=enrollments)

    with pytest.raises(EnrollmentNotCancellable):
        await uc.execute(
            SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="r")
        )


async def test_double_submit_second_call_raises_not_cancellable_no_second_fee_line() -> None:
    enrollments = _FakeEnrollments([_enrollment()])
    billing = _FakeBilling()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=2500, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=1)}),
        billing=billing,
        clock=lambda: now,
    )

    await uc.execute(
        SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="first")
    )
    assert len(billing.fee_calls) == 1

    with pytest.raises(EnrollmentNotCancellable):
        await uc.execute(
            SelfCancelEnrollmentCommand(
                enrollment_id="enr-1", parent_id="parent-1", reason="second"
            )
        )

    # No second fee line appended for the rejected second call.
    assert len(billing.fee_calls) == 1


async def test_self_cancel_releases_seat_and_emits_cancelled_event() -> None:
    """Capacity is a monotonic ``reserved_seats`` counter incremented by
    ``try_reserve_seat``; if a parent self-cancel never releases it the
    session reads full forever and no waitlisted student is ever promoted
    (``EnrollmentCancelled`` is what drives ``PromoteFromWaitlist``)."""
    enrollments = _FakeEnrollments([_enrollment()])
    sessions = _FakeSessions()
    outbox = _FakeOutbox()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=0, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=30)}),
        sessions=sessions,
        outbox=outbox,
        clock=lambda: now,
    )

    await uc.execute(
        SelfCancelEnrollmentCommand(
            enrollment_id="enr-1", parent_id="parent-1", reason="moving away"
        )
    )

    assert sessions.released == ["session-1"]

    [event] = outbox.events
    assert event.name == "Enrollment.EnrollmentCancelled"
    assert event.academy_id == "acad"
    assert event.aggregate_id == "enr-1"
    assert event.payload.enrollment_id == "enr-1"
    assert event.payload.session_id == "session-1"
    assert event.payload.student_id == "student-1"
    assert event.payload.reason == "parent_cancel"


async def test_double_self_cancel_releases_the_seat_only_once() -> None:
    """The seat must be released only when the CAS actually transitioned the
    enrollment — otherwise a double-submitted cancel over-releases and the
    session silently gains a phantom free seat."""
    enrollments = _FakeEnrollments([_enrollment()])
    sessions = _FakeSessions()
    outbox = _FakeOutbox()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=0, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=30)}),
        sessions=sessions,
        outbox=outbox,
        clock=lambda: now,
    )

    await uc.execute(
        SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="first")
    )
    with pytest.raises(EnrollmentNotCancellable):
        await uc.execute(
            SelfCancelEnrollmentCommand(
                enrollment_id="enr-1", parent_id="parent-1", reason="second"
            )
        )

    assert sessions.released == ["session-1"]
    assert len(outbox.events) == 1


class _StaleReadEnrollments(_FakeEnrollments):
    """``get`` keeps reporting 'active' after the CAS has already won once.

    Models the genuine two-tab race rather than a sequential replay. In
    ``execute`` the cheap pre-CAS read at :364 and the CAS at :388 are two
    separate round trips, so the loser of a real race reads a still-active
    row and sails past the pre-CAS check — only the CAS-loser guard stops it.
    A sequential test can never reach that branch, because by then the read
    itself returns 'cancelled'.
    """

    async def get(self, enrollment_id: str) -> Enrollment | None:
        current = self._by_id.get(enrollment_id)
        if current is None:
            return None
        return current.model_copy(update={"status": "active"})


async def test_cas_loser_of_a_true_race_does_not_release_the_seat_again() -> None:
    """Pins the CAS-loser guard specifically.

    The sequential double-cancel test above cannot fail if that guard is
    deleted — the pre-CAS read check absorbs the second call first. This one
    holds the read at 'active' for both callers, so removing the guard lets
    the loser fall through and release a second seat / append a second event.
    """
    enrollments = _StaleReadEnrollments([_enrollment()])
    sessions = _FakeSessions()
    outbox = _FakeOutbox()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=0, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=30)}),
        sessions=sessions,
        outbox=outbox,
        clock=lambda: now,
    )

    await uc.execute(
        SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="first")
    )
    # The loser: its read still says 'active', so only the CAS can stop it.
    with pytest.raises(EnrollmentNotCancellable):
        await uc.execute(
            SelfCancelEnrollmentCommand(
                enrollment_id="enr-1", parent_id="parent-1", reason="second"
            )
        )

    assert sessions.released == ["session-1"]
    assert len(outbox.events) == 1
    assert len(enrollments.cancelled_calls) == 1


async def test_lifecycle_row_failure_does_not_suppress_waitlist_promotion() -> None:
    """The timeline row is cosmetic; the ``EnrollmentCancelled`` append that
    drives waitlist promotion is not. Because the row is written between the
    seat release and that append, letting it propagate would mean a transient
    audit-write failure permanently swallows the promotion — and the retry
    cannot recover it, since the retry loses the CAS.
    """

    class _BrokenEvents:
        def __init__(self) -> None:
            self.attempts = 0

        async def record(self, event: Any) -> None:
            self.attempts += 1
            raise RuntimeError("mongo blipped writing the timeline row")

    events = _BrokenEvents()
    sessions = _FakeSessions()
    outbox = _FakeOutbox()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=_FakeEnrollments([_enrollment()]),
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=0, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=30)}),
        sessions=sessions,
        outbox=outbox,
        enrollment_events=events,  # type: ignore[arg-type]
        clock=lambda: now,
    )

    await uc.execute(
        SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="bye")
    )

    assert events.attempts == 1
    assert sessions.released == ["session-1"]
    assert len(outbox.events) == 1, "promotion event must survive a timeline-row failure"


async def test_capacity_compensation_runs_before_fee_billing_in_exact_order() -> None:
    """Fee billing is explicitly best-effort (see module docstring); the seat
    release is not allowed to be collateral damage of a billing failure.

    Asserting the exact interleaving via a shared call log, rather than just
    the end state: a billing failure is swallowed by ``except Exception``, so
    the end state alone cannot tell a pre-billing release from a post-billing
    one, and the ordering invariant would silently rot.
    """
    call_log: list[str] = []
    enrollments = _FakeEnrollments([_enrollment()])
    sessions = _FakeSessions(call_log=call_log)
    outbox = _FakeOutbox(call_log=call_log)
    events = _FakeLifecycleEvents(call_log=call_log)
    billing = _FakeBillingThatFails(call_log=call_log)
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=2500, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=1)}),
        sessions=sessions,
        outbox=outbox,
        enrollment_events=events,
        billing=billing,  # type: ignore[arg-type]
        clock=lambda: now,
    )

    result = await uc.execute(
        SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="bye")
    )

    assert result.status == "cancelled"
    assert billing.calls == 1
    assert call_log == [
        "release_seat",
        "lifecycle_record",
        "outbox_append",
        "record_cancellation_fee",
    ]


async def test_seat_is_released_even_when_fee_billing_raises_a_base_exception() -> None:
    """``asyncio.CancelledError`` (client disconnect) is a ``BaseException``,
    so the fee-billing ``except Exception`` does not contain it. If the
    capacity compensation ran after billing, that teardown would skip the
    release and strand the seat on an enrollment already cancelled on disk.
    """
    enrollments = _FakeEnrollments([_enrollment()])
    sessions = _FakeSessions()
    outbox = _FakeOutbox()
    billing = _FakeBillingThatFails(asyncio.CancelledError())
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=2500, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=1)}),
        sessions=sessions,
        outbox=outbox,
        billing=billing,  # type: ignore[arg-type]
        clock=lambda: now,
    )

    with pytest.raises(asyncio.CancelledError):
        await uc.execute(
            SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="bye")
        )

    assert billing.calls == 1
    assert sessions.released == ["session-1"]
    assert len(outbox.events) == 1


async def test_capacity_compensation_completes_when_the_request_task_is_cancelled() -> None:
    """A client disconnect cancels the whole request task, which can land
    mid-``release_seat``. The cancel is already committed by then, so the
    compensation is shielded and must still finish — otherwise the seat leaks
    and no waitlisted student is ever promoted into it.
    """
    release_started = asyncio.Event()
    release_may_finish = asyncio.Event()

    class _SlowSessions:
        def __init__(self) -> None:
            self.released: list[str] = []

        async def release_seat(self, session_id: str) -> None:
            release_started.set()
            await release_may_finish.wait()
            self.released.append(session_id)

    sessions = _SlowSessions()
    outbox = _FakeOutbox()
    events = _FakeLifecycleEvents()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=_FakeEnrollments([_enrollment()]),
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=0, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=30)}),
        sessions=sessions,  # type: ignore[arg-type]
        outbox=outbox,
        enrollment_events=events,
        clock=lambda: now,
    )

    task = asyncio.create_task(
        uc.execute(
            SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="bye")
        )
    )
    # Bounded on purpose. A regression that stops calling ``release_seat``
    # never sets this event, and an unbounded wait would HANG the suite
    # instead of failing it — there is no pytest-timeout in backend/.venv and
    # no timeout in pyproject.toml, so the only backstop is the CI job's
    # 15-minute kill, which reports no test name at all.
    await asyncio.wait_for(release_started.wait(), timeout=5)
    task.cancel()  # the parent closed the tab mid-request
    release_may_finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The shielded compensation outlives the request task; let it drain.
    for _ in range(20):
        if outbox.events:
            break
        await asyncio.sleep(0)

    assert sessions.released == ["session-1"]
    assert len(events.recorded) == 1
    assert len(outbox.events) == 1


async def test_release_seat_failure_propagates_on_an_already_committed_cancel() -> None:
    """Deliberate trade-off (module ERROR HANDLING): unlike the fee-billing
    call, a ``release_seat`` failure is NOT swallowed. The parent sees a 500
    on an enrollment that is already cancelled, because a silently skipped
    release is a permanently unsellable seat — ``reserved_seats`` only ever
    ``$inc``s, so nothing downstream re-derives the true count. The retry is
    safe: it loses the status CAS and raises ``EnrollmentNotCancellable``.
    """
    enrollments = _FakeEnrollments([_enrollment()])
    sessions = _FakeSessionsThatFail()
    outbox = _FakeOutbox()
    events = _FakeLifecycleEvents()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=enrollments,
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=0, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=30)}),
        sessions=sessions,  # type: ignore[arg-type]
        outbox=outbox,
        enrollment_events=events,
        clock=lambda: now,
    )

    with pytest.raises(RuntimeError, match="mongo write timed out"):
        await uc.execute(
            SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="bye")
        )

    assert sessions.calls == 1
    # The cancel itself stands — there is no compensating "un-cancel".
    assert len(enrollments.cancelled_calls) == 1
    # Nothing downstream of the failed release ran.
    assert events.recorded == []
    assert outbox.events == []


async def test_self_cancel_records_a_cancelled_lifecycle_event_for_admin_parity() -> None:
    """Admin ``CancelEnrollment`` writes an ``EnrollmentLifecycleEvent``; the
    parent path must too, or the admin timeline shows the waitlist
    ``promoted`` row with no cancellation that explains it."""
    events = _FakeLifecycleEvents()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=_FakeEnrollments([_enrollment()]),
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=0, timing="immediate")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=30)}),
        enrollment_events=events,
        clock=lambda: now,
    )

    await uc.execute(
        SelfCancelEnrollmentCommand(
            enrollment_id="enr-1", parent_id="parent-1", reason="moving away"
        )
    )

    [event] = events.recorded
    assert event.event_type == "cancelled"
    assert event.academy_id == "acad"
    assert event.enrollment_id == "enr-1"
    assert event.session_id == "session-1"
    assert event.student_id == "student-1"
    assert event.actor_id == "parent-1"
    assert event.reason == "moving away"
    assert event.effective_at == now
    assert event.occurred_at == now


async def test_lifecycle_event_effective_at_is_the_end_of_period_cancel_date() -> None:
    """``effective_at`` carries the policy's cancellation date, not the
    request time — so an end_of_period cancel reads as taking effect at
    month end on the admin timeline."""
    events = _FakeLifecycleEvents()
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    uc = _use_case(
        enrollments=_FakeEnrollments([_enrollment()]),
        policies=_FakePolicies(_policy(minimum_notice_days=7, fee_cents=0, timing="end_of_period")),
        occurrences=_FakeOccurrenceForSession({"session-1": now + timedelta(days=30)}),
        enrollment_events=events,
        clock=lambda: now,
    )

    result = await uc.execute(
        SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="bye")
    )

    [event] = events.recorded
    assert event.effective_at == result.cancelled_at
    assert event.effective_at == datetime(2026, 7, 31, 23, 59, 59, 999999, tzinfo=UTC)
    assert event.occurred_at == now


async def test_preview_agrees_with_cancel_same_helper_same_inputs() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    policy = _policy(minimum_notice_days=7, fee_cents=2500, timing="end_of_period")
    occurrences = _FakeOccurrenceForSession({"session-1": now + timedelta(days=2)})

    preview = PreviewSelfCancel(
        enrollments=_FakeEnrollments([_enrollment()]),
        students=_FakeStudents(),
        policies=_FakePolicies(policy),
        occurrences=occurrences,
        clock=lambda: now,
    )
    preview_result = await preview.execute(enrollment_id="enr-1", parent_id="parent-1")

    cancel = _use_case(
        enrollments=_FakeEnrollments([_enrollment()]),
        policies=_FakePolicies(policy),
        occurrences=occurrences,
        billing=_FakeBilling(),
        clock=lambda: now,
    )
    cancel_result = await cancel.execute(
        SelfCancelEnrollmentCommand(enrollment_id="enr-1", parent_id="parent-1", reason="r")
    )

    assert preview_result.notice_met == cancel_result.notice_met is False
    assert preview_result.fee_cents == cancel_result.fee_cents == 2500


async def test_preview_for_other_parents_enrollment_is_404_style() -> None:
    preview = PreviewSelfCancel(
        enrollments=_FakeEnrollments([_enrollment()]),
        students=_FakeStudents([_student(parent_id="parent-1")]),
        policies=_FakePolicies(),
        occurrences=_FakeOccurrenceForSession(),
    )

    with pytest.raises(EnrollmentNotFound):
        await preview.execute(enrollment_id="enr-1", parent_id="someone-else")


async def test_preview_not_allowed_when_enrollment_not_active() -> None:
    preview = PreviewSelfCancel(
        enrollments=_FakeEnrollments([_enrollment(status="cancelled")]),
        students=_FakeStudents(),
        policies=_FakePolicies(),
        occurrences=_FakeOccurrenceForSession(),
    )

    result = await preview.execute(enrollment_id="enr-1", parent_id="parent-1")

    assert result.allowed is False
    assert result.blocked_reason is not None


# ---------------------------------------------------------------------------
# Composition-level idempotency: the REAL billing-port adapter
# (``_SelfCancelFeeBillingPort`` in ``composition/parent.py``), wrapping the
# real ``AddInvoiceLine`` use case against an in-process Mongo. A retried
# ``record_cancellation_fee`` call for the SAME enrollment must never append
# a second fee line (BILLING SAFETY: no double-billing).
# ---------------------------------------------------------------------------


async def test_billing_port_adapter_is_idempotent_against_real_ledger() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    from backend.v2.composition.parent import compose_parent
    from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
    from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
    from backend.v2.shared.tenancy.context import tenant_scope

    academy_id = "acad"
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]

    class _FakeOutbox:
        async def append(self, event: object) -> None:
            return None

    with tenant_scope(academy_id):
        await db["students"].insert_one(
            {
                "academy_id": academy_id,
                "student_id": "student-1",
                "parent_id": "parent-1",
                "full_name": "Kid One",
            }
        )

        composition = compose_parent(
            db,
            _FakeOutbox(),  # type: ignore[arg-type]
            MongoIdempotencyStore(db),
            FakeStripeGateway(),
            academy_id=academy_id,
        )

        enrollment = _enrollment()
        billing_port = composition.self_cancel_enrollment._billing  # type: ignore[attr-defined]
        idempotency_key = "enr-1-self-cancel-fee"

        first = await billing_port.record_cancellation_fee(
            enrollment=enrollment,
            fee_cents=2500,
            reason="Cancellation fee",
            actor_id="parent-1",
            idempotency_key=idempotency_key,
        )
        second = await billing_port.record_cancellation_fee(
            enrollment=enrollment,
            fee_cents=2500,
            reason="Cancellation fee",
            actor_id="parent-1",
            idempotency_key=idempotency_key,
        )

        assert first.get("deduped") is not True
        assert second.get("deduped") is True

        invoice_id = first["invoice_id"]
        lines = await db["invoice_lines"].count_documents(
            {"academy_id": academy_id, "invoice_id": invoice_id, "source_id": idempotency_key}
        )
        assert lines == 1
