"""Parent session catalog + server-priced checkout BFF tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.v2.contexts.enrollment.infrastructure.mongo_session_repo as session_repo_module
from backend.v2.contexts.enrollment.application.use_cases.list_parent_available_sessions import (
    ParentAvailableSession,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import MongoSessionRepository
from backend.v2.contexts.onboarding.domain.errors import MissingSelectedSession
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import tenant_scope


def _claims(role: str = "parent") -> AuthClaims:
    return AuthClaims(
        user_id=f"{role}-1",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


class _FrozenCatalogDateTime(datetime):
    _now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._now.replace(tzinfo=None)
        return cls._now.astimezone(tz)


class _ListAvailableSessions:
    async def execute(self) -> list[ParentAvailableSession]:
        now = datetime.now(UTC)
        return [
            ParentAvailableSession(
                session_id="sess-available",
                title="Junior Badminton",
                location="Court 1",
                start_at=now + timedelta(days=1),
                end_at=now + timedelta(days=1, hours=1),
                capacity=8,
                enrolled_count=3,
                available_seats=5,
                amount_cents=2500,
            )
        ]


@dataclass
class _CheckoutResult:
    payment_id: str = "pay-1"
    checkout_session_id: str = "cs-1"
    redirect_url: str = "https://fake.stripe.com/cs-1"


@dataclass
class _AutopayResult:
    subscription_id: str = "sub-1"
    checkout_session_id: str = "cs_sub_1"
    redirect_url: str = "https://fake.stripe.com/cs-1"


class _ParentUseCases:
    def __init__(self) -> None:
        self.list_available_sessions = _ListAvailableSessions()
        self.checkout_calls: list[dict[str, str]] = []
        self.autopay_calls: list[dict[str, str]] = []

    async def start_checkout_for_application(
        self,
        *,
        parent_id: str,
        application_id: str,
        success_url: str,
        cancel_url: str,
    ) -> _CheckoutResult:
        self.checkout_calls.append(
            {
                "parent_id": parent_id,
                "application_id": application_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
        )
        if application_id == "missing-session":
            raise MissingSelectedSession("application must have a selected session")
        return _CheckoutResult()

    async def list_payments_for_parent(self, _parent_id: str) -> list[object]:
        return []

    async def start_autopay_for_enrollment(
        self,
        *,
        parent_id: str,
        enrollment_id: str,
        success_url: str,
        cancel_url: str,
    ):
        self.autopay_calls.append(
            {
                "parent_id": parent_id,
                "enrollment_id": enrollment_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
        )
        return _AutopayResult()

    async def open_billing_portal(self, *, parent_id: str, return_url: str):
        return {"redirect_url": f"https://fake.stripe.com/portal/{parent_id}?return={return_url}"}

    async def get_checkout_status(self, *, parent_id: str, checkout_session_id: str):
        return {
            "checkout_session_id": checkout_session_id,
            "payment_id": "pay-status",
            "status": "pending",
            "parent_id": parent_id,
        }


@contextmanager
def _make_client(role: str = "parent") -> Iterator[tuple[TestClient, _ParentUseCases]]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    use_cases = _ParentUseCases()
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases
    with TestClient(app) as client:
        yield client, use_cases


def test_parent_lists_available_sessions() -> None:
    with _make_client() as (client, _):
        response = client.get("/api/v2/parent/sessions/available")

    assert response.status_code == 200
    assert response.json()["sessions"] == [
        {
            "session_id": "sess-available",
            "title": "Junior Badminton",
            "location": "Court 1",
            "start_at": response.json()["sessions"][0]["start_at"],
            "end_at": response.json()["sessions"][0]["end_at"],
            "capacity": 8,
            "enrolled_count": 3,
            "available_seats": 5,
            "amount_cents": 2500,
        }
    ]


@pytest.mark.parametrize("role", ["coach", "admin"])
def test_wrong_persona_cannot_list_parent_sessions(role: str) -> None:
    with _make_client(role) as (client, _):
        response = client.get("/api/v2/parent/sessions/available")

    assert response.status_code == 404


def test_checkout_start_rejects_client_amount() -> None:
    with _make_client() as (client, use_cases):
        response = client.post(
            "/api/v2/parent/checkout/start",
            json={
                "application_id": "app-1",
                "amount_cents": 1,
                "success_url": "https://app/success",
                "cancel_url": "https://app/cancel",
            },
        )

    assert response.status_code == 422
    assert use_cases.checkout_calls == []


def test_checkout_start_uses_application_only_payload() -> None:
    with _make_client() as (client, use_cases):
        response = client.post(
            "/api/v2/parent/checkout/start",
            json={
                "application_id": "app-1",
                "success_url": "https://app/success",
                "cancel_url": "https://app/cancel",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "payment_id": "pay-1",
        "redirect_url": "https://fake.stripe.com/cs-1",
    }
    assert use_cases.checkout_calls == [
        {
            "parent_id": "parent-1",
            "application_id": "app-1",
            "success_url": "https://app/success",
            "cancel_url": "https://app/cancel",
        }
    ]
    assert "amount_cents" not in use_cases.checkout_calls[0]


def test_checkout_start_without_selected_session_returns_422() -> None:
    with _make_client() as (client, _):
        response = client.post(
            "/api/v2/parent/checkout/start",
            json={
                "application_id": "missing-session",
                "success_url": "https://app/success",
                "cancel_url": "https://app/cancel",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "Onboarding.MissingSelectedSession"


def test_parent_starts_autopay_for_enrollment() -> None:
    with _make_client() as (client, use_cases):
        response = client.post(
            "/api/v2/parent/autopay/start",
            json={
                "enrollment_id": "enr-1",
                "success_url": "https://app/success",
                "cancel_url": "https://app/cancel",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "subscription_id": "sub-1",
        "checkout_session_id": "cs_sub_1",
        "redirect_url": "https://fake.stripe.com/cs-1",
    }
    assert use_cases.autopay_calls == [
        {
            "parent_id": "parent-1",
            "enrollment_id": "enr-1",
            "success_url": "https://app/success",
            "cancel_url": "https://app/cancel",
        }
    ]


def test_parent_opens_billing_portal() -> None:
    with _make_client() as (client, _):
        response = client.post(
            "/api/v2/parent/billing/portal",
            json={"return_url": "https://app/payments"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["redirect_url"].startswith("https://fake.stripe.com/portal/parent-1")


def test_parent_reads_checkout_status() -> None:
    with _make_client() as (client, _):
        response = client.get("/api/v2/parent/checkout/status/cs_status")

    assert response.status_code == 200, response.text
    assert response.json()["checkout_session_id"] == "cs_status"
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_parent_available_catalog_includes_available_recurring_templates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_repo_module, "datetime", _FrozenCatalogDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-available-recurring"]
    concrete_start = datetime(2026, 6, 2, 15, 0, tzinfo=UTC)
    await db.sessions.insert_many(
        [
            {
                "academy_id": "academy-a",
                "session_id": "sess-concrete",
                "title": "Concrete Session",
                "location": "Court 1",
                "capacity": 6,
                "status": "scheduled",
                "start_at": concrete_start,
                "end_at": concrete_start + timedelta(hours=1),
                "amount_cents": 3300,
            },
            {
                "academy_id": "academy-a",
                "session_id": "tpl-available",
                "name": "Recurring Session",
                "location": "Court 2",
                "max_students": 5,
                "status": "active",
                "days_of_week": ["Mon", "Wed"],
                "start_time": "16:30",
                "end_time": "17:30",
                "monthly_price": 99.5,
                "timezone": "America/Chicago",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            },
            {
                "academy_id": "academy-a",
                "session_id": "tpl-expired",
                "name": "Expired Recurring",
                "max_students": 5,
                "status": "active",
                "days_of_week": ["Mon"],
                "start_time": "16:30",
                "end_time": "17:30",
                "timezone": "America/Chicago",
                "start_date": "2026-05-01",
                "end_date": "2026-05-31",
            },
            {
                "academy_id": "academy-a",
                "session_id": "tpl-not-started",
                "name": "Future Active Recurring",
                "max_students": 5,
                "status": "active",
                "days_of_week": ["Mon"],
                "start_time": "16:30",
                "end_time": "17:30",
                "timezone": "America/Chicago",
                "start_date": "2026-06-15",
                "end_date": "2026-07-31",
            },
            {
                "academy_id": "academy-a",
                "session_id": "tpl-prod-shaped",
                "title": "Production Shaped Recurring",
                "location": "Court 4",
                "capacity": 7,
                "status": "scheduled",
                "days_of_week": ["Mon"],
                "start_time": "11:00",
                "end_time": "12:00",
                "monthly_price_cents": 8800,
                "timezone": "America/Chicago",
                "start_at": datetime(2026, 5, 25, 16, 0, tzinfo=UTC),
                "end_at": datetime(2026, 5, 25, 17, 0, tzinfo=UTC),
            },
            {
                "academy_id": "academy-a",
                "session_id": "tpl-full",
                "name": "Full Recurring",
                "max_students": 1,
                "status": "active",
                "days_of_week": ["Mon"],
                "start_time": "18:00",
                "end_time": "19:00",
            },
            {
                "academy_id": "academy-a",
                "session_id": "tpl-cancelled",
                "name": "Cancelled Recurring",
                "max_students": 5,
                "status": "cancelled",
                "days_of_week": ["Mon"],
                "start_time": "19:00",
                "end_time": "20:00",
            },
            {
                "academy_id": "academy-a",
                "session_id": "tpl-completed",
                "name": "Completed Recurring",
                "max_students": 5,
                "status": "completed",
                "days_of_week": ["Mon"],
                "start_time": "20:00",
                "end_time": "21:00",
            },
            {
                "academy_id": "other-academy",
                "session_id": "tpl-other-tenant",
                "name": "Other Tenant Recurring",
                "max_students": 5,
                "status": "active",
                "days_of_week": ["Mon"],
                "start_time": "21:00",
                "end_time": "22:00",
            },
        ]
    )
    await db.enrollments.insert_many(
        [
            {
                "academy_id": "academy-a",
                "enrollment_id": "enr-active",
                "session_id": "tpl-available",
                "student_id": "st-1",
                "status": "active",
            },
            {
                "academy_id": "academy-a",
                "enrollment_id": "enr-full",
                "session_id": "tpl-full",
                "student_id": "st-2",
                "status": "active",
            },
            {
                "academy_id": "other-academy",
                "enrollment_id": "enr-other",
                "session_id": "tpl-available",
                "student_id": "st-3",
                "status": "active",
            },
        ]
    )

    with tenant_scope("academy-a"):
        rows = await MongoSessionRepository(db).available_for_parent_catalog()

    by_id = {row.session_id: row for row in rows}
    assert set(by_id) == {
        "sess-concrete",
        "tpl-available",
        "tpl-not-started",
        "tpl-prod-shaped",
    }
    assert by_id["tpl-available"].title == "Recurring Session"
    assert by_id["tpl-available"].capacity == 5
    assert by_id["tpl-available"].enrolled_count == 1
    assert by_id["tpl-available"].available_seats == 4
    assert by_id["tpl-available"].amount_cents == 9950
    assert by_id["tpl-available"].start_at == datetime(2026, 6, 1, 21, 30, tzinfo=UTC)
    assert by_id["tpl-not-started"].start_at == datetime(2026, 6, 15, 21, 30, tzinfo=UTC)
    assert by_id["tpl-prod-shaped"].start_at == datetime(2026, 6, 1, 16, 0, tzinfo=UTC)
    assert by_id["tpl-prod-shaped"].amount_cents == 8800


@pytest.mark.asyncio
async def test_parent_available_catalog_filters_full_sessions_before_capping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_repo_module, "datetime", _FrozenCatalogDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-available-cap-after-filter"]
    full_sessions = [
        {
            "academy_id": "academy-a",
            "session_id": f"full-{index}",
            "title": f"Full {index}",
            "capacity": 1,
            "status": "scheduled",
            "start_at": datetime(2026, 6, 2, 10, index % 60, tzinfo=UTC),
            "end_at": datetime(2026, 6, 2, 11, index % 60, tzinfo=UTC),
        }
        for index in range(100)
    ]
    await db.sessions.insert_many(
        [
            *full_sessions,
            {
                "academy_id": "academy-a",
                "session_id": "available-after-full",
                "title": "Available After Full",
                "capacity": 4,
                "status": "scheduled",
                "start_at": datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 3, 11, 0, tzinfo=UTC),
            },
        ]
    )
    await db.enrollments.insert_many(
        [
            {
                "academy_id": "academy-a",
                "enrollment_id": f"enr-full-{index}",
                "session_id": f"full-{index}",
                "student_id": f"st-{index}",
                "status": "active",
            }
            for index in range(100)
        ]
    )

    with tenant_scope("academy-a"):
        rows = await MongoSessionRepository(db).available_for_parent_catalog()

    assert [row.session_id for row in rows] == ["available-after-full"]
