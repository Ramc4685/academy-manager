from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.session_type_ops import (
    CreateSessionType,
    CreateSessionTypeCommand,
    MoveStudentSessionType,
    MoveStudentSessionTypeCommand,
    OverrideStudentPrice,
    OverrideStudentPriceCommand,
    UpdateSessionType,
    UpdateSessionTypeCommand,
)
from backend.v2.contexts.billing.domain.session_type import (
    SessionType,
    StudentBillingEnrollment,
)
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway


def _now() -> datetime:
    return datetime(2026, 5, 16, 9, 0, tzinfo=UTC)


class FakeSessionTypeRepo:
    def __init__(self) -> None:
        self.rows: dict[str, SessionType] = {}

    async def save(self, session_type: SessionType) -> None:
        self.rows[session_type.session_type_id] = session_type

    async def get(self, session_type_id: str) -> SessionType | None:
        return self.rows.get(session_type_id)

    async def list_active(self) -> list[SessionType]:
        return [row for row in self.rows.values() if row.is_active]

    async def soft_delete(self, session_type_id: str) -> None:
        row = self.rows[session_type_id]
        self.rows[session_type_id] = row.model_copy(
            update={"is_active": False, "updated_at": _now()}
        )


class FakeBillingEnrollmentRepo:
    def __init__(self) -> None:
        self.rows: dict[str, StudentBillingEnrollment] = {}

    async def save(self, enrollment: StudentBillingEnrollment) -> None:
        self.rows[enrollment.enrollment_id] = enrollment

    async def get(self, enrollment_id: str) -> StudentBillingEnrollment | None:
        return self.rows.get(enrollment_id)

    async def list_for_student(self, student_id: str) -> list[StudentBillingEnrollment]:
        return [row for row in self.rows.values() if row.student_id == student_id]

    async def list_for_parent(self, parent_id: str) -> list[StudentBillingEnrollment]:
        return [row for row in self.rows.values() if row.parent_id == parent_id]

    async def get_by_stripe_subscription(
        self, stripe_subscription_id: str
    ) -> StudentBillingEnrollment | None:
        for row in self.rows.values():
            if row.stripe_subscription_id == stripe_subscription_id:
                return row
        return None


class FakeEventSink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def record_session_type_changed(self, **kwargs):
        self.events.append(_Event(name="Enrollment.SessionTypeChanged", payload=kwargs))


class _Event:
    def __init__(self, *, name: str, payload: dict[str, Any]) -> None:
        self.name = name
        self.payload = payload


@pytest.mark.asyncio
async def test_create_and_update_session_type() -> None:
    repo = FakeSessionTypeRepo()
    create = CreateSessionType(session_types=repo, academy_id="acad", clock=_now)
    created = await create.execute(
        CreateSessionTypeCommand(
            name="Beginner",
            description="Group class",
            price_cents=12_000,
            billing_period="monthly",
            overage_rate_cents=2_500,
        )
    )

    assert created.session_type_id
    assert created.academy_id == "acad"
    assert created.name == "Beginner"

    update = UpdateSessionType(session_types=repo, clock=_now)
    updated = await update.execute(
        UpdateSessionTypeCommand(
            session_type_id=created.session_type_id,
            name="Beginner Plus",
            price_cents=13_000,
        )
    )

    assert updated.name == "Beginner Plus"
    assert updated.price_cents == 13_000
    assert updated.description == "Group class"


@pytest.mark.asyncio
async def test_override_student_price_updates_billing_enrollment() -> None:
    enrollments = FakeBillingEnrollmentRepo()
    now = _now()
    await enrollments.save(
        StudentBillingEnrollment(
            enrollment_id="bill-1",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            session_type_id="type-1",
            billing_start_date=now,
            enrolled_at=now,
            updated_at=now,
        )
    )

    result = await OverrideStudentPrice(enrollments=enrollments, clock=_now).execute(
        OverrideStudentPriceCommand(enrollment_id="bill-1", override_price_cents=9_500)
    )

    assert result.override_price_cents == 9_500
    assert enrollments.rows["bill-1"].override_price_cents == 9_500


@pytest.mark.asyncio
async def test_move_student_session_type_records_local_proration_without_stripe_invoice() -> None:
    session_types = FakeSessionTypeRepo()
    enrollments = FakeBillingEnrollmentRepo()
    stripe = FakeStripeGateway()
    event_sink = FakeEventSink()
    now = _now()
    await session_types.save(
        SessionType(
            session_type_id="type-basic",
            academy_id="acad",
            name="Basic",
            price_cents=12_000,
            created_at=now,
            updated_at=now,
        )
    )
    await session_types.save(
        SessionType(
            session_type_id="type-elite",
            academy_id="acad",
            name="Elite",
            price_cents=20_000,
            created_at=now,
            updated_at=now,
        )
    )
    await enrollments.save(
        StudentBillingEnrollment(
            enrollment_id="bill-1",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            session_type_id="type-basic",
            stripe_subscription_id="sub_123",
            billing_start_date=now,
            enrolled_at=now,
            updated_at=now,
        )
    )

    result = await MoveStudentSessionType(
        enrollments=enrollments,
        session_types=session_types,
        stripe=stripe,
        event_sink=event_sink,
        clock=_now,
    ).execute(
        MoveStudentSessionTypeCommand(
            enrollment_id="bill-1",
            to_session_type_id="type-elite",
            move_date=datetime(2026, 5, 17, tzinfo=UTC),
            period_start=datetime(2026, 5, 1, tzinfo=UTC),
            period_end=datetime(2026, 6, 1, tzinfo=UTC),
            actor_id="admin-1",
            reason="level up",
        )
    )

    assert result.enrollment.session_type_id == "type-elite"
    assert result.proration.net_cents == 3_871
    assert result.stripe_invoice_id is None
    assert stripe.subscription_prorations == []
    assert [event.name for event in event_sink.events] == ["Enrollment.SessionTypeChanged"]
