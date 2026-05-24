"""Admin reports dashboard BFF tests."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


@pytest.fixture
def reports_admin_client() -> Iterator[TestClient]:
    use_cases = SimpleNamespace(
        get_reports_dashboard=AsyncMock(),
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="admin-1",
        email="admin@example.com",
        academy_id="acad",
        roles=("admin",),
    )
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases
    with TestClient(app) as client:
        client.use_cases = use_cases  # type: ignore[attr-defined]
        yield client


def test_admin_reports_dashboard_returns_owner_finance_and_ops_shape(
    reports_admin_client,
) -> None:
    reports_admin_client.use_cases.get_reports_dashboard = AsyncMock(  # type: ignore[attr-defined]
        return_value={
            "period": "2026-05",
            "cash_collected_cents": 185_00,
            "outstanding_dues_cents": 65_00,
            "attendance": {
                "present_count": 7,
                "recorded_count": 10,
                "attendance_rate": 0.7,
                "empty": False,
            },
            "sessions": {
                "scheduled_count": 4,
                "completed_count": 2,
                "cancelled_count": 1,
                "enrolled_seats": 18,
                "capacity": 24,
                "capacity_utilization": 0.75,
                "empty": False,
            },
            "empty_states": [],
        }
    )

    response = reports_admin_client.get("/api/v2/admin/reports/dashboard?period=2026-05")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "period": "2026-05",
        "cash_collected_cents": 18500,
        "outstanding_dues_cents": 6500,
        "attendance": {
            "present_count": 7,
            "recorded_count": 10,
            "attendance_rate": 0.7,
            "empty": False,
        },
        "sessions": {
            "scheduled_count": 4,
            "completed_count": 2,
            "cancelled_count": 1,
            "enrolled_seats": 18,
            "capacity": 24,
            "capacity_utilization": 0.75,
            "empty": False,
        },
        "empty_states": [],
    }
    reports_admin_client.use_cases.get_reports_dashboard.assert_awaited_once_with("2026-05")  # type: ignore[attr-defined]


def test_admin_reports_dashboard_empty_state(reports_admin_client) -> None:
    reports_admin_client.use_cases.get_reports_dashboard = AsyncMock(  # type: ignore[attr-defined]
        return_value={
            "period": "2026-05",
            "cash_collected_cents": 0,
            "outstanding_dues_cents": 0,
            "attendance": {
                "present_count": 0,
                "recorded_count": 0,
                "attendance_rate": None,
                "empty": True,
            },
            "sessions": {
                "scheduled_count": 0,
                "completed_count": 0,
                "cancelled_count": 0,
                "enrolled_seats": 0,
                "capacity": 0,
                "capacity_utilization": None,
                "empty": True,
            },
            "empty_states": [
                "No collected payment rows found for this month.",
                "No attendance marks found for this month.",
                "No sessions found for this month.",
            ],
        }
    )

    response = reports_admin_client.get("/api/v2/admin/reports/dashboard?period=2026-05")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cash_collected_cents"] == 0
    assert body["attendance"]["attendance_rate"] is None
    assert body["sessions"]["capacity_utilization"] is None
    assert body["empty_states"] == [
        "No collected payment rows found for this month.",
        "No attendance marks found for this month.",
        "No sessions found for this month.",
    ]


def test_admin_reports_dashboard_rejects_invalid_period(reports_admin_client) -> None:
    response = reports_admin_client.get("/api/v2/admin/reports/dashboard?period=May-2026")

    assert response.status_code == 422
