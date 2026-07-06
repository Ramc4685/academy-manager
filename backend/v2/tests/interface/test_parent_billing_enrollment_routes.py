"""Interface tests for POST /parent/billing-enrollments and cancel."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.enroll_child_in_session_type import (
    CancelBillingEnrollment,
    EnrollChildInSessionType,
)
from backend.v2.contexts.billing.domain.session_type import SessionType, StudentBillingEnrollment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

# ParentUseCases is a dataclass — instantiate with None for unused fields.

_NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# In-memory fakes (same as application tests, minimal)
# ---------------------------------------------------------------------------


@dataclass
class _FakeEnrollmentRepo:
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
class _FakeSessionTypeRepo:
    rows: dict[str, SessionType] = field(default_factory=dict)

    async def save(self, st: SessionType) -> None:
        self.rows[st.session_type_id] = st

    async def get(self, session_type_id: str) -> SessionType | None:
        return self.rows.get(session_type_id)

    async def list_active(self) -> list[SessionType]:
        return [st for st in self.rows.values() if st.is_active]

    async def soft_delete(self, session_type_id: str) -> None:
        st = self.rows[session_type_id]
        self.rows[session_type_id] = st.model_copy(update={"is_active": False})


class _FakeOwnerLookup:
    def __init__(self, owned: dict[str, set[str]]) -> None:
        self._owned = owned

    async def is_owned(self, parent_id: str, student_id: str) -> bool:
        return student_id in self._owned.get(parent_id, set())


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_active_session_type() -> SessionType:
    return SessionType(
        session_type_id="st-1",
        academy_id="acad",
        name="Beginner Group",
        price_cents=5000,
        billing_period="monthly",
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_inactive_session_type() -> SessionType:
    return SessionType(
        session_type_id="st-inactive",
        academy_id="acad",
        name="Inactive Group",
        price_cents=5000,
        billing_period="monthly",
        is_active=False,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_use_cases(
    enroll_child_uc: EnrollChildInSessionType,
    cancel_uc: CancelBillingEnrollment,
) -> ParentUseCases:
    """Build a ParentUseCases with None for all unused fields."""
    return ParentUseCases(
        start_application=None,  # type: ignore[arg-type]
        patch_application=None,  # type: ignore[arg-type]
        get_application_status=None,  # type: ignore[arg-type]
        transition_application=None,  # type: ignore[arg-type]
        start_checkout=None,  # type: ignore[arg-type]
        quote_enrollment=None,
        start_checkout_for_application=None,
        start_autopay_for_enrollment=None,
        open_billing_portal=None,
        get_checkout_status=None,
        handle_webhook_event=None,  # type: ignore[arg-type]
        list_available_sessions=None,  # type: ignore[arg-type]
        list_payments_for_parent=None,
        list_credits_for_parent=None,
        list_children_for_parent=None,
        list_enrollments_for_parent=None,
        request_enrollment_pause=None,  # type: ignore[arg-type]
        list_parent_pause_requests=None,  # type: ignore[arg-type]
        submit_absence_notice=None,  # type: ignore[arg-type]
        list_parent_absences=None,  # type: ignore[arg-type]
        submit_makeup_request=None,  # type: ignore[arg-type]
        list_parent_makeups=None,  # type: ignore[arg-type]
        list_eligible_makeup_targets=None,  # type: ignore[arg-type]
        list_attendance_for_parent=None,
        list_progress_for_parent=None,
        list_invoices_for_parent=None,
        get_invoice_for_parent=None,
        get_child_schedule=None,
        enroll_child=enroll_child_uc.execute,
        cancel_billing_enrollment=cancel_uc.execute,
        get_parent_waiver_requirement=None,  # type: ignore[arg-type]
        accept_parent_waiver=None,  # type: ignore[arg-type]
        get_academy_info=None,
        submit_trial_request=None,  # type: ignore[arg-type]
        list_parent_trial_requests=None,  # type: ignore[arg-type]
    )


def _build_app(
    claims: AuthClaims,
    use_cases: ParentUseCases,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases
    return app


def _parent_claims(user_id: str = "parent-1") -> AuthClaims:
    return AuthClaims(
        user_id=user_id,
        email=f"{user_id}@example.com",
        academy_id="acad",
        roles=("parent",),
    )


@pytest.fixture()
def setup():
    enrollments = _FakeEnrollmentRepo()
    stripe = FakeStripeGateway()
    st_repo = _FakeSessionTypeRepo()
    st_repo.rows["st-1"] = _make_active_session_type()
    st_repo.rows["st-inactive"] = _make_inactive_session_type()

    ownership = _FakeOwnerLookup({"parent-1": {"student-1"}})

    enroll_uc = EnrollChildInSessionType(
        enrollments=enrollments,
        session_types=st_repo,
        stripe=stripe,
        student_owner_lookup=ownership,
        academy_id="acad",
        clock=lambda: _NOW,
    )
    cancel_uc = CancelBillingEnrollment(
        enrollments=enrollments,
        stripe=stripe,
        clock=lambda: _NOW,
    )

    use_cases = _make_use_cases(enroll_uc, cancel_uc)
    return {
        "enrollments": enrollments,
        "stripe": stripe,
        "use_cases": use_cases,
    }


@pytest.fixture()
def client(setup) -> Iterator[TestClient]:
    app = _build_app(_parent_claims(), setup["use_cases"])
    with TestClient(app, raise_server_exceptions=True) as c:
        c.enrollments = setup["enrollments"]  # type: ignore[attr-defined]
        c.stripe = setup["stripe"]  # type: ignore[attr-defined]
        yield c


# ---------------------------------------------------------------------------
# GET /parent/academy
# ---------------------------------------------------------------------------


def test_parent_academy_uses_request_tenant(client, setup):
    setup["use_cases"].get_academy_info = AsyncMock(
        return_value={
            "display_name": "Request Academy",
            "timezone": "America/Chicago",
            "contact_email": "hello@example.com",
            "contact_phone": None,
            "hours_text": None,
            "address": None,
            "logo_url": None,
        }
    )

    resp = client.get("/api/v2/parent/academy")

    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Request Academy"
    assert resp.json()["timezone"] == "America/Chicago"
    setup["use_cases"].get_academy_info.assert_awaited_once_with(academy_id="acad")


def test_parent_academy_timezone_null_when_not_configured(client, setup):
    setup["use_cases"].get_academy_info = AsyncMock(
        return_value={
            "display_name": "Request Academy",
            "contact_email": None,
            "contact_phone": None,
            "hours_text": None,
            "address": None,
            "logo_url": None,
        }
    )

    resp = client.get("/api/v2/parent/academy")

    assert resp.status_code == 200
    assert resp.json()["timezone"] is None


# ---------------------------------------------------------------------------
# POST /parent/billing-enrollments
# ---------------------------------------------------------------------------


def test_enroll_creates_enrollment_and_returns_redirect(client):
    resp = client.post(
        "/api/v2/parent/billing-enrollments",
        json={
            "student_id": "student-1",
            "session_type_id": "st-1",
            "success_url": "https://example.com/success",
            "cancel_url": "https://example.com/cancel",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "redirect_url" in body
    assert body["redirect_url"].startswith("https://")
    assert "enrollment_id" in body
    assert body["status"] == "active"


def test_enroll_non_owned_student_returns_404(client):
    resp = client.post(
        "/api/v2/parent/billing-enrollments",
        json={
            "student_id": "student-OTHER",
            "session_type_id": "st-1",
            "success_url": "https://example.com/success",
            "cancel_url": "https://example.com/cancel",
        },
    )
    assert resp.status_code == 404


def test_enroll_inactive_session_type_returns_400(client):
    resp = client.post(
        "/api/v2/parent/billing-enrollments",
        json={
            "student_id": "student-1",
            "session_type_id": "st-inactive",
            "success_url": "https://example.com/success",
            "cancel_url": "https://example.com/cancel",
        },
    )
    assert resp.status_code == 400


def test_enroll_missing_session_type_returns_404(client):
    resp = client.post(
        "/api/v2/parent/billing-enrollments",
        json={
            "student_id": "student-1",
            "session_type_id": "st-missing",
            "success_url": "https://example.com/success",
            "cancel_url": "https://example.com/cancel",
        },
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /parent/billing-enrollments/{enrollment_id}/cancel
# ---------------------------------------------------------------------------


def _seed_enrollment(client, parent_id: str = "parent-1") -> str:
    enrollment = StudentBillingEnrollment(
        enrollment_id="enr-seeded",
        academy_id="acad",
        student_id="student-1",
        parent_id=parent_id,
        session_type_id="st-1",
        stripe_subscription_id="sub_test_abc",
        billing_start_date=_NOW,
        status="active",
        enrolled_at=_NOW,
        updated_at=_NOW,
    )
    client.enrollments.rows["enr-seeded"] = enrollment
    return "enr-seeded"


def test_cancel_sets_status_and_calls_stripe(client):
    enrollment_id = _seed_enrollment(client)
    resp = client.post(f"/api/v2/parent/billing-enrollments/{enrollment_id}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["enrollment_id"] == enrollment_id

    # Stripe called
    assert len(client.stripe.cancelled_subscriptions) == 1
    assert client.stripe.cancelled_subscriptions[0]["at_period_end"] is True


def test_cancel_cross_parent_returns_404(setup):
    """parent-2 cannot cancel parent-1's enrollment."""
    enrollments = setup["enrollments"]
    enrollment = StudentBillingEnrollment(
        enrollment_id="enr-p1",
        academy_id="acad",
        student_id="student-1",
        parent_id="parent-1",
        session_type_id="st-1",
        stripe_subscription_id="sub_test_xyz",
        billing_start_date=_NOW,
        status="active",
        enrolled_at=_NOW,
        updated_at=_NOW,
    )
    enrollments.rows["enr-p1"] = enrollment

    # Build app with parent-2 claims
    app = _build_app(_parent_claims("parent-2"), setup["use_cases"])
    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.post("/api/v2/parent/billing-enrollments/enr-p1/cancel")
    assert resp.status_code == 404


def test_cancel_missing_enrollment_returns_404(client):
    resp = client.post("/api/v2/parent/billing-enrollments/enr-missing/cancel")
    assert resp.status_code == 404
