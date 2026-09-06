"""Interface tests for the family billing routes (spec §3, §5, §8)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.family_billing import FamilyBillingUnavailable
from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import (
    NothingToPause,
    PauseFamilyAutopayResult,
)
from backend.v2.interfaces.admin.families_routes import get_admin_families
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _view() -> dict[str, Any]:
    return {
        "generated_at": "2026-09-10T15:00:00+00:00",
        "timezone": "America/Chicago",
        "today": "2026-09-10",
        "parent": {"parent_id": "p-1", "name": "Sahaya", "email": "s@example.com", "phone": None},
        "header": {
            "balance_cents": 6000,
            "open_invoice_count": 1,
            "available_credit_cents": 0,
            "last_payment": None,
            "autopay": {
                "state": "on",
                "active_count": 1,
                "total_count": 1,
                "card_last4": "4242",
                "card_label": "Visa",
                "next_charge_on": "2026-09-08",
                "next_charge_invoice_id": "inv-1",
                "last_failure": None,
            },
            "registration": {"state": "registered", "card_on_file": True, "last_invited_at": None},
            "enrollment_counts": {"active": 1, "paused": 0, "cancelled": 0},
        },
        "students": [
            {
                "student_id": "s-1",
                "name": "Arjun",
                "status": "active",
                "enrollments": [
                    {
                        "enrollment_id": "e-1",
                        "session_id": "sess-1",
                        "session_title": "Sat 9:00",
                        "schedule": "Sat 09:00",
                        "status": "active",
                        "monthly_price_cents": 6000,
                        "override_price_cents": None,
                        "autopay_status": "active",
                        "recurring_discount": None,
                        "resume_on": None,
                        "actions": ["recurring_discount"],
                    }
                ],
            }
        ],
        "invoices": [
            {
                "invoice_id": "inv-1",
                "invoice_number": "INV-1",
                "period": "2026-09",
                "student_id": "s-1",
                "student_name": "Arjun",
                "enrollment_id": "e-1",
                "status": "open",
                "total_cents": 6000,
                "paid_cents": 0,
                "balance_due_cents": 6000,
                "due_date": "2026-09-08",
                "created_at": "2026-09-01T06:00:00+00:00",
                "paid_at": None,
                "voided_at": None,
                "void_reason": None,
                "settlement_unlinked": False,
                "delivery": {
                    "status": "sent",
                    "last_sent_at": "2026-09-01T06:05:00+00:00",
                    "kind": "autopay_notice",
                },
                "allocations": [],
                "credits": [],
                "chargeable": True,
                "actions": ["send", "record_payment", "charge_card", "void", "discount_once"],
            }
        ],
        "timeline": [
            {
                "at": "2026-09-01T06:00:00+00:00",
                "kind": "money",
                "code": "invoice_generated",
                "summary": "Sep 2026 invoice generated · Arjun · $60",
                "invoice_id": "inv-1",
                "invoice_ids": ["inv-1"],
                "enrollment_id": None,
                "student_name": "Arjun",
                "actor_id": None,
                "reason": None,
                "amount_cents": 6000,
                "muted": False,
            }
        ],
        "actions": ["autopay_off", "send_invoice", "record_payment"],
        "warnings": [],
        "internal_marker": True,
    }


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.result: dict[str, Any] | None = _view()
        self.error: Exception | None = None

    async def build(self, parent_id: str) -> dict[str, Any] | None:
        self.calls.append(parent_id)
        if self.error:
            raise self.error
        return self.result


class FakePause:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    async def execute(self, **kwargs: Any) -> PauseFamilyAutopayResult:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return PauseFamilyAutopayResult(paused_count=2, active_count_before=2, warnings=[])


class FakeServices:
    def __init__(self) -> None:
        self.reader = FakeReader()
        self.pause_autopay = FakePause()


def _claims(*roles: str) -> AuthClaims:
    return AuthClaims(user_id="u-1", email="u@example.com", academy_id="acad", roles=tuple(roles))  # type: ignore[arg-type]


def _make_app(roles: tuple[str, ...], services: FakeServices) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(*roles)
    app.dependency_overrides[get_admin_families] = lambda: services
    return app


@pytest.fixture
def services() -> FakeServices:
    return FakeServices()


@pytest.fixture
def admin(services: FakeServices) -> Iterator[TestClient]:
    with TestClient(_make_app(("admin",), services)) as c:
        yield c


@pytest.fixture
def owner(services: FakeServices) -> Iterator[TestClient]:
    with TestClient(_make_app(("admin", "owner"), services)) as c:
        yield c


@pytest.fixture
def coach(services: FakeServices) -> Iterator[TestClient]:
    with TestClient(_make_app(("coach",), services)) as c:
        yield c


def test_owner_gets_every_action(owner: TestClient, services: FakeServices) -> None:
    resp = owner.get("/api/v2/admin/families/p-1/billing")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parent"]["parent_id"] == "p-1"
    assert body["invoices"][0]["actions"] == [
        "send",
        "record_payment",
        "charge_card",
        "void",
        "discount_once",
    ]
    assert body["students"][0]["enrollments"][0]["actions"] == ["recurring_discount"]
    assert "internal_marker" not in body
    assert services.reader.calls == ["p-1"]


def test_admin_loses_owner_only_actions(admin: TestClient) -> None:
    body = admin.get("/api/v2/admin/families/p-1/billing").json()
    assert body["invoices"][0]["actions"] == ["send", "record_payment", "charge_card"]
    assert body["students"][0]["enrollments"][0]["actions"] == []
    assert body["actions"] == ["autopay_off", "send_invoice", "record_payment"]


def test_coach_is_404(coach: TestClient, services: FakeServices) -> None:
    assert coach.get("/api/v2/admin/families/p-1/billing").status_code == 404
    assert services.reader.calls == []


def test_unknown_parent_is_404(admin: TestClient, services: FakeServices) -> None:
    services.reader.result = None
    assert admin.get("/api/v2/admin/families/nobody/billing").status_code == 404


def test_primary_source_failure_is_503(admin: TestClient, services: FakeServices) -> None:
    services.reader.error = FamilyBillingUnavailable("invoices down")
    assert admin.get("/api/v2/admin/families/p-1/billing").status_code == 503


def test_pause_autopay_happy_path(admin: TestClient, services: FakeServices) -> None:
    resp = admin.post(
        "/api/v2/admin/families/p-1/autopay/pause",
        json={"reason": "parent asked", "request_id": "req-1"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"paused_count": 2, "active_count_before": 2, "warnings": []}
    assert services.pause_autopay.calls == [
        {
            "academy_id": "acad",
            "parent_id": "p-1",
            "actor_id": "u-1",
            "reason": "parent asked",
            "request_id": "req-1",
        }
    ]


def test_pause_autopay_requires_reason(admin: TestClient, services: FakeServices) -> None:
    resp = admin.post(
        "/api/v2/admin/families/p-1/autopay/pause", json={"reason": "", "request_id": "req-1"}
    )
    assert resp.status_code == 422
    assert services.pause_autopay.calls == []


def test_pause_autopay_nothing_to_pause_is_400(admin: TestClient, services: FakeServices) -> None:
    services.pause_autopay.error = NothingToPause("no_active_autopay: nothing")
    resp = admin.post(
        "/api/v2/admin/families/p-1/autopay/pause", json={"reason": "x", "request_id": "r"}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "no_active_autopay"


def test_pause_autopay_is_404_for_coach(coach: TestClient, services: FakeServices) -> None:
    resp = coach.post(
        "/api/v2/admin/families/p-1/autopay/pause", json={"reason": "x", "request_id": "r"}
    )
    assert resp.status_code == 404
    assert services.pause_autopay.calls == []
