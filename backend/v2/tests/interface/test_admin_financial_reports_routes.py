"""Phase-3 admin financial report BFF route tests."""

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
def reports_client() -> Iterator[TestClient]:
    use_cases = SimpleNamespace(
        get_refunds_report=AsyncMock(),
        get_revenue_by_category_report=AsyncMock(),
        get_deposit_slip_report=AsyncMock(),
        export_report_csv=AsyncMock(),
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="admin-1",
        email="admin@example.com",
        academy_id="acad",
        roles=("admin", "owner"),  # pre-split admin: migration 0165 grants owner
    )
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases
    with TestClient(app) as client:
        client.use_cases = use_cases  # type: ignore[attr-defined]
        yield client


def test_refunds_report_returns_report_shape(reports_client) -> None:
    reports_client.use_cases.get_refunds_report = AsyncMock(
        return_value={
            "period": "2026-05",
            "total_refunded_cents": 2_500,
            "refund_count": 1,
            "refunds": [
                {
                    "refund_at": "2026-05-10T15:00:00+00:00",
                    "invoice_id": "inv-1",
                    "invoice_number": "BLNO-202605-001",
                    "payment_id": "lpay-1",
                    "parent_id": "parent-1",
                    "student_id": "student-1",
                    "amount_cents": 2_500,
                    "reason": "duplicate charge",
                    "actor_id": "admin-1",
                }
            ],
            "total_credit_cents": 1_500,
            "credit_count": 1,
            "credits": [
                {
                    "credit_id": "cred-1",
                    "created_at": "2026-05-18T00:00:00+00:00",
                    "parent_id": "parent-1",
                    "student_id": None,
                    "invoice_id": None,
                    "type": "withdrawal_credit",
                    "status": "approved",
                    "amount_cents": 1_500,
                    "remaining_amount_cents": 1_500,
                    "reason": "mid-month withdrawal",
                }
            ],
        }
    )

    response = reports_client.get("/api/v2/admin/reports/refunds?period=2026-05")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_refunded_cents"] == 2_500
    assert payload["refunds"][0]["invoice_number"] == "BLNO-202605-001"
    assert payload["credits"][0]["credit_id"] == "cred-1"
    reports_client.use_cases.get_refunds_report.assert_awaited_once_with("2026-05")


def test_revenue_by_category_returns_rows(reports_client) -> None:
    reports_client.use_cases.get_revenue_by_category_report = AsyncMock(
        return_value={
            "period": "2026-05",
            "total_allocated_cents": 15_000,
            "unapplied_cents": 3_000,
            "rows": [
                {"category": "tuition", "category_label": "Tuition", "amount_cents": 14_500},
                {"category": "registration_fee", "category_label": None, "amount_cents": 500},
            ],
        }
    )

    response = reports_client.get("/api/v2/admin/reports/revenue-by-category?period=2026-05")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_allocated_cents"] == 15_000
    assert payload["rows"][0]["category"] == "tuition"


def test_deposit_slip_returns_days(reports_client) -> None:
    reports_client.use_cases.get_deposit_slip_report = AsyncMock(
        return_value={
            "period": "2026-05",
            "total_cents": 16_500,
            "count": 3,
            "days": [
                {
                    "date": "2026-05-04",
                    "total_cents": 16_500,
                    "count": 3,
                    "methods": [
                        {"method": "card", "amount_cents": 14_000, "count": 2},
                        {"method": "cash", "amount_cents": 2_500, "count": 1},
                    ],
                }
            ],
        }
    )

    response = reports_client.get("/api/v2/admin/reports/deposit-slip?period=2026-05")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["days"][0]["methods"][0]["method"] == "card"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v2/admin/reports/refunds?period=2026-13",
        "/api/v2/admin/reports/revenue-by-category?period=2026-00",
        "/api/v2/admin/reports/deposit-slip?period=bad",
        "/api/v2/admin/reports/refunds?period=0000-01",
        "/api/v2/admin/reports/refunds",
    ],
)
def test_financial_reports_reject_invalid_period(reports_client, path) -> None:
    response = reports_client.get(path)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "report_name",
    ["refunds", "revenue-by-category", "deposit-slip", "quickbooks"],
)
def test_export_allowlist_covers_new_reports(reports_client, report_name) -> None:
    reports_client.use_cases.export_report_csv = AsyncMock(return_value="a,b\n")

    response = reports_client.get(f"/api/v2/admin/reports/{report_name}.csv?period=2026-05")

    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{report_name}-2026-05.csv"'
    )
    reports_client.use_cases.export_report_csv.assert_awaited_once_with(report_name, "2026-05")


def test_export_without_period_passes_none(reports_client) -> None:
    reports_client.use_cases.export_report_csv = AsyncMock(return_value="a,b\n")

    response = reports_client.get("/api/v2/admin/reports/quickbooks.csv")

    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == 'attachment; filename="quickbooks.csv"'
    reports_client.use_cases.export_report_csv.assert_awaited_once_with("quickbooks", None)


def test_export_unknown_report_is_404(reports_client) -> None:
    response = reports_client.get("/api/v2/admin/reports/not-a-report.csv")
    assert response.status_code == 404, response.text


def test_export_invalid_period_is_422(reports_client) -> None:
    response = reports_client.get("/api/v2/admin/reports/quickbooks.csv?period=2026-13")
    assert response.status_code == 422, response.text
