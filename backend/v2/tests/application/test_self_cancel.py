"""Application/domain tests for parent self-cancel enrollment (R4).

Covers the pure ``compute_self_cancel_terms`` helper and the
``SelfCancelEnrollment`` use case: happy path, fee line via the (fake)
billing port, immediate vs end_of_period timing, ownership/status guards,
CAS double-submit protection, and preview/cancel parity.
"""

from __future__ import annotations

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
    error or an ``AddInvoiceLine`` ``ValueError`` in the real adapter."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or RuntimeError("mongo write timed out")
        self.calls = 0

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
        raise self.error


def _use_case(
    *,
    enrollments: _FakeEnrollments | None = None,
    students: _FakeStudents | None = None,
    policies: _FakePolicies | None = None,
    occurrences: _FakeOccurrenceForSession | None = None,
    billing: _FakeBilling | None = None,
    clock=lambda: datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
) -> SelfCancelEnrollment:
    return SelfCancelEnrollment(
        enrollments=enrollments or _FakeEnrollments(),
        students=students or _FakeStudents(),
        policies=policies or _FakePolicies(),
        occurrences=occurrences or _FakeOccurrenceForSession(),
        billing=billing,
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
