from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.session_type import (
    SessionType,
    StudentBillingEnrollment,
)
from backend.v2.contexts.billing.infrastructure.mongo_session_type_repo import (
    MongoSessionTypeRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.shared.tenancy import tenant_scope


def _now() -> datetime:
    return datetime(2026, 5, 16, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_session_type_repo_crud_is_tenant_isolated(db, acad) -> None:
    repo = MongoSessionTypeRepository(db)
    now = _now()
    await repo.save(
        SessionType(
            session_type_id="type-beginner",
            academy_id=acad,
            name="Beginner",
            description="Group beginner class",
            price_cents=12_000,
            billing_period="monthly",
            created_at=now,
            updated_at=now,
        )
    )

    stored = await repo.get("type-beginner")
    assert stored is not None
    assert stored.name == "Beginner"
    assert [row.session_type_id for row in await repo.list_active()] == ["type-beginner"]

    with tenant_scope("other-academy"):
        other_repo = MongoSessionTypeRepository(db)
        assert await other_repo.get("type-beginner") is None
        assert await other_repo.list_active() == []

    await repo.soft_delete("type-beginner")
    assert await repo.list_active() == []


@pytest.mark.asyncio
async def test_student_billing_enrollment_repo_reads_are_tenant_isolated(db, acad) -> None:
    repo = MongoStudentBillingEnrollmentRepository(db)
    now = _now()
    await repo.save(
        StudentBillingEnrollment(
            enrollment_id="bill-enroll-1",
            academy_id=acad,
            student_id="student-1",
            parent_id="parent-1",
            session_type_id="type-beginner",
            stripe_subscription_id="sub_123",
            billing_start_date=now,
            enrolled_at=now,
            updated_at=now,
        )
    )

    assert (await repo.get("bill-enroll-1")) is not None
    assert [row.enrollment_id for row in await repo.list_for_student("student-1")] == [
        "bill-enroll-1"
    ]
    assert [row.enrollment_id for row in await repo.list_for_parent("parent-1")] == [
        "bill-enroll-1"
    ]
    assert (await repo.get_by_stripe_subscription("sub_123")).enrollment_id == "bill-enroll-1"  # type: ignore[union-attr]

    with tenant_scope("other-academy"):
        other_repo = MongoStudentBillingEnrollmentRepository(db)
        assert await other_repo.get("bill-enroll-1") is None
        assert await other_repo.list_for_student("student-1") == []
        assert await other_repo.list_for_parent("parent-1") == []
        assert await other_repo.get_by_stripe_subscription("sub_123") is None
