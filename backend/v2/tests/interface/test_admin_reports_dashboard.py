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
        get_session_economics=AsyncMock(),
        get_projected_income=AsyncMock(),
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
                "waitlist_count": 3,
                "empty": False,
            },
            "expenses": {
                "total_cents": 4_500,
                "by_category": [{"category": "rent", "amount_cents": 4_500, "count": 1}],
            },
            "collections_risk": {
                "overdue_family_count": 2,
                "overdue_cents": 65_00,
                "failed_payment_count": 1,
                "partial_payment_count": 1,
                "aging_buckets": [
                    {"label": "Current", "amount_cents": 0, "family_count": 0},
                    {"label": "1-30", "amount_cents": 65_00, "family_count": 2},
                ],
            },
            "profit_and_loss": {
                "revenue_cents": 185_00,
                "coach_payroll_cents": 7_500,
                "rent_cents": 4_500,
                "misc_expenses_cents": 0,
                "net_profit_cents": 6_500,
                "profit_margin": 0.3514,
            },
            "payroll": {
                "estimated_cents": 10_000,
                "approved_cents": 7_500,
                "paid_cents": 2_500,
                "unpaid_cents": 5_000,
                "blocked_by": None,
            },
            "empty_states": [],
        }
    )

    response = reports_admin_client.get("/api/v2/admin/reports/dashboard?period=2026-05")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "period": "2026-05",
        "cash_collected_cents": 18500,
        "billed_cents": 0,
        "collection_rate": None,
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
            "waitlist_count": 3,
            "empty": False,
        },
        "expenses": {
            "total_cents": 4500,
            "by_category": [{"category": "rent", "amount_cents": 4500, "count": 1}],
        },
        "collections_risk": {
            "overdue_family_count": 2,
            "overdue_cents": 6500,
            "failed_payment_count": 1,
            "partial_payment_count": 1,
            "aging_buckets": [
                {"label": "Current", "amount_cents": 0, "family_count": 0, "families": []},
                {"label": "1-30", "amount_cents": 6500, "family_count": 2, "families": []},
            ],
        },
        "profit_and_loss": {
            "revenue_cents": 18500,
            "coach_payroll_cents": 7500,
            "rent_cents": 4500,
            "misc_expenses_cents": 0,
            "net_profit_cents": 6500,
            "profit_margin": 0.3514,
        },
        "payroll": {
            "estimated_cents": 10000,
            "approved_cents": 7500,
            "paid_cents": 2500,
            "unpaid_cents": 5000,
            "blocked_by": None,
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
                "waitlist_count": 0,
                "empty": True,
            },
            "expenses": {"total_cents": 0, "by_category": []},
            "collections_risk": {
                "overdue_family_count": 0,
                "overdue_cents": 0,
                "failed_payment_count": 0,
                "partial_payment_count": 0,
                "aging_buckets": [],
            },
            "profit_and_loss": {
                "revenue_cents": 0,
                "coach_payroll_cents": None,
                "rent_cents": 0,
                "misc_expenses_cents": 0,
                "net_profit_cents": None,
                "profit_margin": None,
            },
            "payroll": {
                "estimated_cents": None,
                "approved_cents": None,
                "paid_cents": None,
                "unpaid_cents": None,
                "blocked_by": "No generated payout periods for this month.",
            },
            "empty_states": [
                "No collected payment rows found for this month.",
                "No attendance marks found for this month.",
                "No sessions found for this month.",
                "No expenses found for this month.",
                "No payout periods generated for this month.",
            ],
        }
    )

    response = reports_admin_client.get("/api/v2/admin/reports/dashboard?period=2026-05")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cash_collected_cents"] == 0
    assert body["attendance"]["attendance_rate"] is None
    assert body["sessions"]["capacity_utilization"] is None
    assert body["profit_and_loss"]["net_profit_cents"] is None
    assert body["payroll"]["blocked_by"] == "No generated payout periods for this month."
    assert body["empty_states"] == [
        "No collected payment rows found for this month.",
        "No attendance marks found for this month.",
        "No sessions found for this month.",
        "No expenses found for this month.",
        "No payout periods generated for this month.",
    ]


def test_admin_reports_dashboard_rejects_invalid_period(reports_admin_client) -> None:
    response = reports_admin_client.get("/api/v2/admin/reports/dashboard?period=May-2026")

    assert response.status_code == 422


def test_admin_session_economics_returns_session_level_finance_shape(
    reports_admin_client,
) -> None:
    reports_admin_client.use_cases.get_session_economics = AsyncMock(  # type: ignore[attr-defined]
        return_value={
            "period": "2026-04",
            "summary": {
                "expected_revenue_cents": 137_000,
                "paid_cents": 100_000,
                "unpaid_cents": 37_000,
                "coach_payroll_cents": 41_100,
                "rent_cents": 10_000,
                "other_expenses_cents": 5_000,
                "expected_profit_cents": 80_900,
                "profit_margin": 0.5905,
            },
            "sessions": [
                {
                    "session_id": "sess-beginner",
                    "title": "Wednesday Beginner",
                    "coach_name": "Kishore",
                    "active_enrollment_count": 1,
                    "paid_student_count": 1,
                    "unpaid_student_count": 0,
                    "monthly_fee_cents": 60_000,
                    "payable_occurrence_count": 4,
                    "expected_revenue_per_occurrence_cents": 15_000,
                    "expected_revenue_cents": 60_000,
                    "paid_cents": 60_000,
                    "unpaid_cents": 0,
                    "coach_payroll_cents": 18_000,
                    "rent_cents": 4_380,
                    "other_expenses_cents": 2_190,
                    "expected_profit_cents": 35_430,
                    "profit_margin": 0.5905,
                }
            ],
            "empty_states": [],
        }
    )

    response = reports_admin_client.get("/api/v2/admin/reports/session-economics?period=2026-04")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"] == "2026-04"
    assert body["summary"]["expected_revenue_cents"] == 137000
    assert body["sessions"][0]["expected_revenue_per_occurrence_cents"] == 15000
    reports_admin_client.use_cases.get_session_economics.assert_awaited_once_with(  # type: ignore[attr-defined]
        "2026-04"
    )


def test_admin_session_economics_rejects_invalid_period(reports_admin_client) -> None:
    response = reports_admin_client.get("/api/v2/admin/reports/session-economics?period=April-2026")

    assert response.status_code == 422


def test_admin_projected_income_returns_autopay_manual_split(reports_admin_client) -> None:
    reports_admin_client.use_cases.get_projected_income = AsyncMock(  # type: ignore[attr-defined]
        return_value={
            "period": "2026-08",
            "total_cents": 120_000,
            "autopay_cents": 90_000,
            "manual_cents": 30_000,
            "enrollment_count": 4,
            "autopay_enrollment_count": 3,
            "manual_enrollment_count": 1,
            "by_session": [
                {
                    "session_id": "sess-beginner",
                    "title": "Wednesday Beginner",
                    "monthly_fee_cents": 30_000,
                    "enrollment_count": 4,
                    "expected_cents": 120_000,
                }
            ],
            "empty": False,
        }
    )

    response = reports_admin_client.get("/api/v2/admin/reports/projected-income?period=2026-08")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_cents"] == 120000
    assert body["autopay_cents"] == 90000
    assert body["manual_cents"] == 30000
    assert body["by_session"][0]["session_id"] == "sess-beginner"
    assert body["empty"] is False
    reports_admin_client.use_cases.get_projected_income.assert_awaited_once_with(  # type: ignore[attr-defined]
        "2026-08"
    )


def test_admin_projected_income_rejects_invalid_period(reports_admin_client) -> None:
    response = reports_admin_client.get("/api/v2/admin/reports/projected-income?period=Aug-2026")

    assert response.status_code == 422


def test_admin_projected_income_unavailable_returns_503(reports_admin_client) -> None:
    reports_admin_client.use_cases.get_projected_income = None  # type: ignore[attr-defined]

    response = reports_admin_client.get("/api/v2/admin/reports/projected-income?period=2026-08")

    assert response.status_code == 503


def test_admin_projected_income_rejects_non_admin_persona() -> None:
    use_cases = SimpleNamespace(get_projected_income=AsyncMock())
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="parent-1",
        email="parent@example.com",
        academy_id="acad",
        roles=("parent",),
    )
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases
    with TestClient(app) as client:
        response = client.get("/api/v2/admin/reports/projected-income?period=2026-08")

    # require_persona deliberately answers 404 (not 403) to avoid leaking route existence.
    assert response.status_code == 404
    use_cases.get_projected_income.assert_not_awaited()
