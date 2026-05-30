from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.billing.domain.session_type import (
    SessionType,
    StudentBillingEnrollment,
)
from backend.v2.contexts.billing.domain.session_type_proration import (
    SessionTypeMoveProrationResult,
)


def _now() -> datetime:
    return datetime(2026, 5, 16, 9, 0, tzinfo=UTC)


class _CreateSessionType:
    async def execute(self, cmd):
        return SessionType(
            session_type_id="type-new",
            academy_id="acad",
            name=cmd.name,
            description=cmd.description,
            price_cents=cmd.price_cents,
            billing_period=cmd.billing_period,
            overage_rate_cents=cmd.overage_rate_cents,
            created_at=_now(),
            updated_at=_now(),
        )


class _ListSessionTypes:
    async def execute(self):
        return [
            SessionType(
                session_type_id="type-new",
                academy_id="acad",
                name="Elite",
                price_cents=20_000,
                billing_period="monthly",
                created_at=_now(),
                updated_at=_now(),
            )
        ]


class _UpdateSessionType:
    async def execute(self, cmd):
        return SessionType(
            session_type_id=cmd.session_type_id,
            academy_id="acad",
            name=cmd.name or "Elite",
            price_cents=cmd.price_cents or 20_000,
            billing_period="monthly",
            is_active=True,
            created_at=_now(),
            updated_at=_now(),
        )


class _SoftDeleteSessionType:
    async def execute(self, session_type_id: str):
        assert session_type_id == "type-new"


class _ListStudentBillingEnrollments:
    async def execute(self, *, student_id=None, parent_id=None):
        _ = student_id
        return [
            StudentBillingEnrollment(
                enrollment_id="bill-1",
                academy_id="acad",
                student_id="student-1",
                parent_id=parent_id or "parent-1",
                session_type_id="type-new",
                stripe_subscription_id="sub_123",
                billing_start_date=_now(),
                enrolled_at=_now(),
                updated_at=_now(),
            )
        ]


class _MoveStudentSessionType:
    async def execute(self, cmd):
        return _Result(
            enrollment=StudentBillingEnrollment(
                enrollment_id=cmd.enrollment_id,
                academy_id="acad",
                student_id="student-1",
                parent_id="parent-1",
                session_type_id=cmd.to_session_type_id,
                stripe_subscription_id="sub_123",
                billing_start_date=_now(),
                enrolled_at=_now(),
                updated_at=_now(),
            ),
            proration=SessionTypeMoveProrationResult(
                credit_cents=5_806,
                charge_cents=9_677,
                net_cents=3_871,
                remaining_days=15,
                total_days=31,
                proration_ratio="15/31",
                from_session_type_id="type-basic",
                to_session_type_id=cmd.to_session_type_id,
            ),
            stripe_invoice_id="in_proration_1",
        )


class _OverrideStudentPrice:
    async def execute(self, cmd):
        return StudentBillingEnrollment(
            enrollment_id=cmd.enrollment_id,
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            session_type_id="type-new",
            override_price_cents=cmd.override_price_cents,
            billing_start_date=_now(),
            enrolled_at=_now(),
            updated_at=_now(),
        )


class _Result:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def _install_session_type_fakes(client) -> None:
    client.use_cases.create_session_type = _CreateSessionType()
    client.use_cases.list_session_types = _ListSessionTypes()
    client.use_cases.update_session_type = _UpdateSessionType()
    client.use_cases.soft_delete_session_type = _SoftDeleteSessionType()
    client.use_cases.list_student_billing_enrollments = _ListStudentBillingEnrollments()
    client.use_cases.move_student_session_type = _MoveStudentSessionType()
    client.use_cases.override_student_price = _OverrideStudentPrice()


def test_admin_session_type_crud_routes(admin_client):
    _install_session_type_fakes(admin_client)

    created = admin_client.post(
        "/api/v2/admin/session-types",
        json={
            "name": "Elite",
            "description": "Elite monthly",
            "price_cents": 20_000,
            "billing_period": "monthly",
            "overage_rate_cents": 2_500,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["session_type_id"] == "type-new"

    listed = admin_client.get("/api/v2/admin/session-types")
    assert listed.status_code == 200, listed.text
    assert listed.json()["session_types"][0]["name"] == "Elite"

    updated = admin_client.patch(
        "/api/v2/admin/session-types/type-new",
        json={"name": "Elite Plus", "price_cents": 21_000},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Elite Plus"

    deleted = admin_client.delete("/api/v2/admin/session-types/type-new")
    assert deleted.status_code == 204


def test_admin_billing_enrollment_move_and_override_routes(admin_client):
    _install_session_type_fakes(admin_client)

    listed = admin_client.get("/api/v2/admin/billing-enrollments?parent_id=parent-1")
    assert listed.status_code == 200, listed.text
    assert listed.json()["enrollments"][0]["enrollment_id"] == "bill-1"

    moved = admin_client.post(
        "/api/v2/admin/billing-enrollments/bill-1/move",
        json={
            "to_session_type_id": "type-elite",
            "move_date": "2026-05-17T00:00:00Z",
            "period_start": "2026-05-01T00:00:00Z",
            "period_end": "2026-06-01T00:00:00Z",
            "reason": "level up",
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["proration"]["net_cents"] == 3_871
    assert moved.json()["stripe_invoice_id"] == "in_proration_1"

    overridden = admin_client.post(
        "/api/v2/admin/billing-enrollments/bill-1/override",
        json={"override_price_cents": 9_500},
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["override_price_cents"] == 9_500


def test_admin_session_types_wrong_persona_returns_404(coach_on_admin_client):
    response = coach_on_admin_client.get("/api/v2/admin/session-types")
    assert response.status_code == 404
