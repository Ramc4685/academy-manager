"""Application-layer tests for EnrollChildInSessionType and CancelBillingEnrollment."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.enroll_child_in_session_type import (
    CancelBillingEnrollment,
    EnrollChildCommand,
    EnrollChildInSessionType,
)
from backend.v2.contexts.billing.domain.errors import (
    SessionTypeInactive,
    SessionTypeNotFound,
    StudentBillingEnrollmentNotFound,
)
from backend.v2.contexts.billing.domain.session_type import SessionType, StudentBillingEnrollment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway

# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeEnrollmentRepo:
    rows: dict[str, StudentBillingEnrollment] = field(default_factory=dict)

    async def save(self, enrollment: StudentBillingEnrollment) -> None:
        self.rows[enrollment.enrollment_id] = enrollment

    async def get(self, enrollment_id: str) -> StudentBillingEnrollment | None:
        return self.rows.get(enrollment_id)

    async def list_for_student(self, student_id: str) -> list[StudentBillingEnrollment]:
        return [e for e in self.rows.values() if e.student_id == student_id]

    async def list_for_parent(self, parent_id: str) -> list[StudentBillingEnrollment]:
        return [e for e in self.rows.values() if e.parent_id == parent_id]

    async def get_by_stripe_subscription(
        self, stripe_subscription_id: str
    ) -> StudentBillingEnrollment | None:
        return next(
            (e for e in self.rows.values() if e.stripe_subscription_id == stripe_subscription_id),
            None,
        )


@dataclass
class FakeSessionTypeRepo:
    rows: dict[str, SessionType] = field(default_factory=dict)

    async def save(self, session_type: SessionType) -> None:
        self.rows[session_type.session_type_id] = session_type

    async def get(self, session_type_id: str) -> SessionType | None:
        return self.rows.get(session_type_id)

    async def list_active(self) -> list[SessionType]:
        return [st for st in self.rows.values() if st.is_active]

    async def soft_delete(self, session_type_id: str) -> None:
        st = self.rows[session_type_id]
        self.rows[session_type_id] = st.model_copy(update={"is_active": False})


class FakeOwnershipLookup:
    def __init__(self, owned: dict[str, set[str]]) -> None:
        # owned[parent_id] = {student_id, ...}
        self._owned = owned

    async def is_owned(self, parent_id: str, student_id: str) -> bool:
        return student_id in self._owned.get(parent_id, set())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


def _make_session_type(*, is_active: bool = True) -> SessionType:
    return SessionType(
        session_type_id="st-1",
        academy_id="acad",
        name="Beginner Group",
        price_cents=5000,
        billing_period="monthly",
        is_active=is_active,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_use_case(
    *,
    enrollments: FakeEnrollmentRepo | None = None,
    session_type: SessionType | None = None,
    stripe: FakeStripeGateway | None = None,
    owned: dict[str, set[str]] | None = None,
) -> EnrollChildInSessionType:
    if enrollments is None:
        enrollments = FakeEnrollmentRepo()
    if stripe is None:
        stripe = FakeStripeGateway()

    st_repo = FakeSessionTypeRepo()
    if session_type is not None:
        st_repo.rows[session_type.session_type_id] = session_type

    ownership = FakeOwnershipLookup(owned or {"parent-1": {"student-1"}})

    return EnrollChildInSessionType(
        enrollments=enrollments,
        session_types=st_repo,
        stripe=stripe,
        student_owner_lookup=ownership,
        academy_id="acad",
        clock=lambda: _NOW,
    )


# ---------------------------------------------------------------------------
# EnrollChildInSessionType tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enroll_creates_enrollment_and_returns_redirect_url():
    enrollments = FakeEnrollmentRepo()
    stripe = FakeStripeGateway()
    uc = _make_use_case(enrollments=enrollments, session_type=_make_session_type(), stripe=stripe)

    result = await uc.execute(
        EnrollChildCommand(
            parent_id="parent-1",
            student_id="student-1",
            session_type_id="st-1",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )
    )

    # Redirect URL is returned
    assert result["redirect_url"].startswith("https://")

    # Enrollment persisted with status active
    enrollment = result["enrollment"]
    assert enrollment.status == "active"
    assert enrollment.parent_id == "parent-1"
    assert enrollment.student_id == "student-1"
    assert enrollment.session_type_id == "st-1"
    assert enrollment.stripe_subscription_id is not None

    # Enrollment is in repo
    persisted = await enrollments.get(enrollment.enrollment_id)
    assert persisted is not None
    assert persisted.status == "active"

    # Stripe was called with correct URLs
    assert len(stripe.subscription_checkouts) == 1
    assert stripe.subscription_checkouts[0]["success_url"] == "https://example.com/success"
    assert stripe.subscription_checkouts[0]["cancel_url"] == "https://example.com/cancel"


@pytest.mark.asyncio
async def test_enroll_non_owned_student_raises_not_found():
    uc = _make_use_case(
        session_type=_make_session_type(),
        owned={"parent-1": {"student-1"}},
    )

    with pytest.raises(StudentBillingEnrollmentNotFound):
        await uc.execute(
            EnrollChildCommand(
                parent_id="parent-1",
                student_id="student-OTHER",  # not owned
                session_type_id="st-1",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )
        )


@pytest.mark.asyncio
async def test_enroll_inactive_session_type_raises_bad_request():
    uc = _make_use_case(session_type=_make_session_type(is_active=False))

    with pytest.raises(SessionTypeInactive):
        await uc.execute(
            EnrollChildCommand(
                parent_id="parent-1",
                student_id="student-1",
                session_type_id="st-1",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )
        )


@pytest.mark.asyncio
async def test_enroll_missing_session_type_raises_not_found():
    uc = _make_use_case(session_type=None)

    with pytest.raises(SessionTypeNotFound):
        await uc.execute(
            EnrollChildCommand(
                parent_id="parent-1",
                student_id="student-1",
                session_type_id="st-missing",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )
        )


# ---------------------------------------------------------------------------
# CancelBillingEnrollment tests
# ---------------------------------------------------------------------------


def _persisted_enrollment(
    *,
    enrollment_id: str = "enr-1",
    parent_id: str = "parent-1",
    stripe_subscription_id: str | None = "sub_test_123",
    status: str = "active",
) -> StudentBillingEnrollment:
    return StudentBillingEnrollment(
        enrollment_id=enrollment_id,
        academy_id="acad",
        student_id="student-1",
        parent_id=parent_id,
        session_type_id="st-1",
        stripe_subscription_id=stripe_subscription_id,
        billing_start_date=_NOW,
        status=status,  # type: ignore[arg-type]
        enrolled_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.asyncio
async def test_cancel_sets_status_and_calls_stripe():
    enrollments = FakeEnrollmentRepo()
    enrollment = _persisted_enrollment()
    enrollments.rows[enrollment.enrollment_id] = enrollment
    stripe = FakeStripeGateway()

    uc = CancelBillingEnrollment(enrollments=enrollments, stripe=stripe, clock=lambda: _NOW)
    await uc.execute(parent_id="parent-1", enrollment_id="enr-1")

    # Status updated to cancelled
    updated = await enrollments.get("enr-1")
    assert updated is not None
    assert updated.status == "cancelled"

    # Stripe cancel called with at_period_end=True
    assert len(stripe.cancelled_subscriptions) == 1
    assert stripe.cancelled_subscriptions[0]["stripe_subscription_id"] == "sub_test_123"
    assert stripe.cancelled_subscriptions[0]["at_period_end"] is True


@pytest.mark.asyncio
async def test_cancel_cross_parent_raises_not_found():
    enrollments = FakeEnrollmentRepo()
    enrollment = _persisted_enrollment(parent_id="parent-1")
    enrollments.rows[enrollment.enrollment_id] = enrollment
    stripe = FakeStripeGateway()

    uc = CancelBillingEnrollment(enrollments=enrollments, stripe=stripe, clock=lambda: _NOW)

    with pytest.raises(StudentBillingEnrollmentNotFound):
        await uc.execute(parent_id="parent-OTHER", enrollment_id="enr-1")


@pytest.mark.asyncio
async def test_cancel_missing_enrollment_raises_not_found():
    enrollments = FakeEnrollmentRepo()
    stripe = FakeStripeGateway()

    uc = CancelBillingEnrollment(enrollments=enrollments, stripe=stripe, clock=lambda: _NOW)

    with pytest.raises(StudentBillingEnrollmentNotFound):
        await uc.execute(parent_id="parent-1", enrollment_id="enr-missing")


@pytest.mark.asyncio
async def test_cancel_already_cancelled_is_idempotent():
    """Cancelling an already-cancelled enrollment returns it without calling Stripe."""
    enrollments = FakeEnrollmentRepo()
    enrollment = _persisted_enrollment(status="cancelled")
    enrollments.rows[enrollment.enrollment_id] = enrollment
    stripe = FakeStripeGateway()

    uc = CancelBillingEnrollment(enrollments=enrollments, stripe=stripe, clock=lambda: _NOW)
    result = await uc.execute(parent_id="parent-1", enrollment_id="enr-1")

    # Returns the already-cancelled enrollment
    assert result.status == "cancelled"
    assert result.enrollment_id == "enr-1"

    # Stripe was NOT called
    assert len(stripe.cancelled_subscriptions) == 0


@pytest.mark.asyncio
async def test_cancel_without_stripe_subscription_updates_status_only():
    """Enrollment without stripe sub still gets status=cancelled, no stripe call."""
    enrollments = FakeEnrollmentRepo()
    enrollment = _persisted_enrollment(stripe_subscription_id=None)
    enrollments.rows[enrollment.enrollment_id] = enrollment
    stripe = FakeStripeGateway()

    uc = CancelBillingEnrollment(enrollments=enrollments, stripe=stripe, clock=lambda: _NOW)
    await uc.execute(parent_id="parent-1", enrollment_id="enr-1")

    updated = await enrollments.get("enr-1")
    assert updated is not None
    assert updated.status == "cancelled"
    assert len(stripe.cancelled_subscriptions) == 0
