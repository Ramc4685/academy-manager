"""Parent session catalog + server-priced checkout BFF tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.list_parent_available_sessions import (
    ParentAvailableSession,
)
from backend.v2.contexts.onboarding.domain.errors import MissingSelectedSession
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str = "parent") -> AuthClaims:
    return AuthClaims(
        user_id=f"{role}-1",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


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
