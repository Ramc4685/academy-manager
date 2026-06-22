from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import (
    BillingDeferral,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_billing_deferral_repo import (
    MongoBillingDeferralRepository,
)
from backend.v2.shared.tenancy import tenant_scope


def _now() -> datetime:
    return datetime(2026, 6, 22, 14, 0, tzinfo=UTC)


def test_new_billing_deferral_requires_resume_review_or_expiry() -> None:
    with pytest.raises(ValidationError, match="resume_on, review_on, or expires_on"):
        BillingDeferral(
            deferral_id="def-1",
            enrollment_id="enroll-1",
            student_id="student-1",
            deferral_type="admin_pause",
            reason="travel",
            source="admin_direct_pause",
            actor_id="admin-1",
            billing_period="2026-06",
            created_at=_now(),
        )


def test_billing_deferral_active_window_excludes_expired_rows() -> None:
    active = BillingDeferral(
        deferral_id="def-1",
        enrollment_id="enroll-1",
        student_id="student-1",
        deferral_type="fixed_pause",
        reason="travel",
        source="pause_request",
        source_id="pause-1",
        actor_id="admin-1",
        billing_period="2026-06",
        resume_on=date(2026, 7, 15),
        created_at=_now(),
    )
    expired = active.model_copy(
        update={
            "deferral_id": "def-2",
            "billing_period": "2026-05",
            "expires_on": date(2026, 5, 31),
            "resume_on": None,
        }
    )

    assert active.covers_period("2026-06", today=date(2026, 6, 22))
    assert not expired.covers_period("2026-06", today=date(2026, 6, 22))


@pytest.mark.asyncio
async def test_mongo_billing_deferral_repo_round_trips_and_closes_by_tenant() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["billing-deferrals"]
    repo = MongoBillingDeferralRepository(db)
    deferral = BillingDeferral(
        deferral_id="def-1",
        enrollment_id="enroll-1",
        student_id="student-1",
        deferral_type="fixed_pause",
        reason="travel",
        source="pause_request",
        source_id="pause-1",
        actor_id="admin-1",
        billing_period="2026-06",
        resume_on=date(2026, 7, 15),
        created_at=_now(),
    )

    with tenant_scope("acad-1"):
        await repo.add(deferral)
        loaded = await repo.active_for_enrollment_period(
            enrollment_id="enroll-1",
            period="2026-06",
            today=date(2026, 6, 22),
        )
    with tenant_scope("acad-2"):
        isolated = await repo.active_for_enrollment_period(
            enrollment_id="enroll-1",
            period="2026-06",
            today=date(2026, 6, 22),
        )
    with tenant_scope("acad-1"):
        await repo.close_active_for_enrollment(
            enrollment_id="enroll-1",
            closed_at=_now(),
            closed_by="system",
            reason="resume_succeeded",
        )
        closed = await repo.active_for_enrollment_period(
            enrollment_id="enroll-1",
            period="2026-06",
            today=date(2026, 6, 22),
        )

    assert loaded is not None
    assert loaded.deferral_id == "def-1"
    assert isolated is None
    assert closed is None
