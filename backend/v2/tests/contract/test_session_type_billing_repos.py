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


async def _seed_enrollment(
    repo: MongoStudentBillingEnrollmentRepository,
    *,
    enrollment_id: str,
    academy_id: str,
    autopay_enrollment_status: str = "active",
    parent_id: str = "parent-1",
) -> None:
    now = _now()
    await repo.save(
        StudentBillingEnrollment(
            enrollment_id=enrollment_id,
            academy_id=academy_id,
            student_id="student-1",
            parent_id=parent_id,
            session_type_id="type-beginner",
            billing_start_date=now,
            autopay_enrollment_status=autopay_enrollment_status,  # type: ignore[arg-type]
            enrolled_at=now,
            updated_at=now,
        )
    )


@pytest.mark.asyncio
async def test_set_autopay_enrollment_status_applies_legal_transition(db, acad) -> None:
    repo = MongoStudentBillingEnrollmentRepository(db)
    await _seed_enrollment(
        repo, enrollment_id="e1", academy_id=acad, autopay_enrollment_status="active"
    )

    applied = await repo.set_autopay_enrollment_status(enrollment_id="e1", status="paused")

    assert applied is True
    assert await repo.get_autopay_enrollment_status(enrollment_id="e1") == "paused"


@pytest.mark.asyncio
async def test_set_autopay_enrollment_status_drops_illegal_transition(db, acad) -> None:
    repo = MongoStudentBillingEnrollmentRepository(db)
    await _seed_enrollment(
        repo, enrollment_id="e1", academy_id=acad, autopay_enrollment_status="disabled"
    )

    # disabled -> paused is illegal; must be a logged no-op returning False.
    applied = await repo.set_autopay_enrollment_status(enrollment_id="e1", status="paused")

    assert applied is False
    assert await repo.get_autopay_enrollment_status(enrollment_id="e1") == "disabled"


@pytest.mark.asyncio
async def test_set_autopay_enrollment_status_unknown_enrollment_returns_false(db, acad) -> None:
    repo = MongoStudentBillingEnrollmentRepository(db)
    applied = await repo.set_autopay_enrollment_status(enrollment_id="missing", status="paused")
    assert applied is False


@pytest.mark.asyncio
async def test_set_autopay_enrollment_status_rejects_stale_read_race(db, acad, monkeypatch) -> None:
    repo = MongoStudentBillingEnrollmentRepository(db)
    await _seed_enrollment(
        repo, enrollment_id="e1", academy_id=acad, autopay_enrollment_status="active"
    )
    original_update_one = repo._update_one
    raced = False

    async def racing_update_one(filter_, update, **kwargs):
        nonlocal raced
        if not raced and filter_.get("enrollment_id") == "e1":
            raced = True
            await db["student_billing_enrollments"].update_one(
                {"academy_id": acad, "enrollment_id": "e1"},
                {"$set": {"autopay_enrollment_status": "disabled"}},
            )
        return await original_update_one(filter_, update, **kwargs)

    monkeypatch.setattr(repo, "_update_one", racing_update_one)

    applied = await repo.set_autopay_enrollment_status(enrollment_id="e1", status="paused")

    assert applied is False
    assert await repo.get_autopay_enrollment_status(enrollment_id="e1") == "disabled"


@pytest.mark.asyncio
async def test_record_attempt_outcome_leaves_enrollment_status_untouched(db, acad) -> None:
    repo = MongoStudentBillingEnrollmentRepository(db)
    await _seed_enrollment(
        repo, enrollment_id="e1", academy_id=acad, autopay_enrollment_status="active"
    )

    await repo.record_attempt_outcome(
        enrollment_id="e1",
        outcome="declined",
        occurred_at=datetime(2026, 6, 15, tzinfo=UTC),
        failure_code="card_declined",
    )

    stored = await repo.get("e1")
    assert stored is not None
    assert stored.autopay_enrollment_status == "active"
    assert stored.last_attempt_outcome == "declined"
    assert stored.last_failure_code == "card_declined"
    assert stored.last_attempt_at is not None


@pytest.mark.asyncio
async def test_mark_autopay_active_from_setup_walks_disabled_to_active(db, acad) -> None:
    """Review-fix 6(b): a disabled enrollment completing setup must reach active
    via the guarded walk (disabled -> offered -> setup_started -> active)."""
    repo = MongoStudentBillingEnrollmentRepository(db)
    await _seed_enrollment(
        repo, enrollment_id="e1", academy_id=acad, autopay_enrollment_status="disabled"
    )

    ok = await repo.mark_autopay_active_from_setup(enrollment_id="e1")

    assert ok is True
    assert await repo.get_autopay_enrollment_status(enrollment_id="e1") == "active"


@pytest.mark.asyncio
async def test_mark_autopay_active_from_setup_from_setup_started(db, acad) -> None:
    repo = MongoStudentBillingEnrollmentRepository(db)
    await _seed_enrollment(
        repo, enrollment_id="e1", academy_id=acad, autopay_enrollment_status="setup_started"
    )

    ok = await repo.mark_autopay_active_from_setup(enrollment_id="e1")

    assert ok is True
    assert await repo.get_autopay_enrollment_status(enrollment_id="e1") == "active"


@pytest.mark.asyncio
async def test_autopay_status_writes_are_tenant_isolated(db, acad) -> None:
    repo = MongoStudentBillingEnrollmentRepository(db)
    await _seed_enrollment(
        repo, enrollment_id="shared", academy_id=acad, autopay_enrollment_status="active"
    )

    with tenant_scope("other-academy"):
        other_repo = MongoStudentBillingEnrollmentRepository(db)
        # No such enrollment in the other tenant — guarded write is a no-op.
        assert (
            await other_repo.set_autopay_enrollment_status(enrollment_id="shared", status="paused")
        ) is False
        assert await other_repo.get_autopay_enrollment_status(enrollment_id="shared") is None

    # Academy A's enrollment is unchanged by the cross-tenant attempt.
    assert await repo.get_autopay_enrollment_status(enrollment_id="shared") == "active"
