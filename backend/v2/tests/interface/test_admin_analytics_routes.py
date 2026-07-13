"""Admin analytics routes — interface tests (Phase 2 Task 5)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.finance.application.use_cases.attendance_trends import (
    AttendancePeriodPoint,
    AttendanceTrendsResult,
)
from backend.v2.contexts.finance.application.use_cases.coach_utilization import (
    CoachUtilizationPoint,
    CoachUtilizationResult,
)
from backend.v2.contexts.finance.application.use_cases.enrollment_funnel import (
    EnrollmentFunnelResult,
)
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FUNNEL_RESULT = EnrollmentFunnelResult(
    leads=10,
    applied=7,
    assessed=4,
    confirmed=3,
    dropped=2,
    total_applications=26,
    conversion_rate=Decimal("0.1154"),
    period=None,
)

_TRENDS_RESULT = AttendanceTrendsResult(
    periods=[
        AttendancePeriodPoint(
            period="2026-01",
            scheduled_count=20,
            completed_count=18,
            no_show_count=2,
            completion_rate=Decimal("0.9000"),
        )
    ],
    overall_completion_rate=Decimal("0.9000"),
)

_UTILIZATION_RESULT = CoachUtilizationResult(
    coaches=[
        CoachUtilizationPoint(
            coach_id="coach-1",
            period="2026-01",
            hours=Decimal("32"),
            payout_minor=160000,
            utilization_rate=Decimal("0.8000"),
        )
    ],
    periods=["2026-01"],
    total_payout_minor=160000,
)


def _make_client(
    *,
    roles: tuple[str, ...] = ("admin",),
    use_cases: object | None = None,
) -> TestClient:
    uc = use_cases or SimpleNamespace(
        get_enrollment_funnel=AsyncMock(return_value=_FUNNEL_RESULT),
        get_attendance_trends=AsyncMock(return_value=_TRENDS_RESULT),
        get_coach_utilization=AsyncMock(return_value=_UTILIZATION_RESULT),
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="admin-1",
        email="admin@example.com",
        academy_id="acad",
        roles=roles,
    )
    app.dependency_overrides[get_admin_use_cases] = lambda: uc
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def analytics_client() -> TestClient:
    return _make_client()


# ---------------------------------------------------------------------------
# Enrollment funnel
# ---------------------------------------------------------------------------


def test_enrollment_funnel_returns_result(analytics_client: TestClient) -> None:
    resp = analytics_client.get("/api/v2/admin/reports/enrollment-funnel")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["leads"] == 10
    assert body["confirmed"] == 3
    assert body["total_applications"] == 26
    assert body["period"] is None


def test_admin_report_export_allows_known_reports() -> None:
    export = AsyncMock(return_value="header\nvalue\n")
    client = _make_client(use_cases=SimpleNamespace(export_report_csv=export))

    resp = client.get("/api/v2/admin/reports/attendance.csv")

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    assert resp.text == "header\nvalue\n"
    export.assert_awaited_once_with("attendance", None)


def test_admin_report_export_rejects_unknown_report_without_calling_use_case() -> None:
    export = AsyncMock(return_value="error\n")
    client = _make_client(use_cases=SimpleNamespace(export_report_csv=export))

    resp = client.get("/api/v2/admin/reports/all-tenants.csv")

    assert resp.status_code == 404
    export.assert_not_awaited()


def test_admin_report_export_requires_admin_persona() -> None:
    export = AsyncMock(return_value="header\nvalue\n")
    client = _make_client(roles=("parent",), use_cases=SimpleNamespace(export_report_csv=export))

    resp = client.get("/api/v2/admin/reports/attendance.csv")

    assert resp.status_code == 404
    export.assert_not_awaited()


def test_enrollment_funnel_with_period(analytics_client: TestClient) -> None:
    uc = SimpleNamespace(
        get_enrollment_funnel=AsyncMock(
            return_value=EnrollmentFunnelResult(
                leads=5,
                applied=3,
                assessed=2,
                confirmed=1,
                dropped=0,
                total_applications=11,
                conversion_rate=Decimal("0.0909"),
                period="2026-01",
            )
        )
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
    app.dependency_overrides[get_admin_use_cases] = lambda: uc
    with TestClient(app) as client:
        resp = client.get("/api/v2/admin/reports/enrollment-funnel?period=2026-01")
    assert resp.status_code == 200, resp.text
    assert resp.json()["period"] == "2026-01"
    uc.get_enrollment_funnel.assert_awaited_once_with("2026-01")


# ---------------------------------------------------------------------------
# Attendance trends
# ---------------------------------------------------------------------------


def test_attendance_trends_returns_result(analytics_client: TestClient) -> None:
    resp = analytics_client.get("/api/v2/admin/reports/attendance-trends?periods=2026-01")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["periods"]) == 1
    assert body["periods"][0]["period"] == "2026-01"
    assert body["periods"][0]["scheduled_count"] == 20
    assert body["overall_completion_rate"] == pytest.approx(0.9, abs=1e-3)


def test_attendance_trends_multiple_periods(analytics_client: TestClient) -> None:
    uc = SimpleNamespace(
        get_attendance_trends=AsyncMock(
            return_value=AttendanceTrendsResult(
                periods=[
                    AttendancePeriodPoint(
                        period="2026-01",
                        scheduled_count=10,
                        completed_count=9,
                        no_show_count=1,
                        completion_rate=Decimal("0.9000"),
                    ),
                    AttendancePeriodPoint(
                        period="2026-02",
                        scheduled_count=8,
                        completed_count=6,
                        no_show_count=2,
                        completion_rate=Decimal("0.7500"),
                    ),
                ],
                overall_completion_rate=Decimal("0.8333"),
            )
        )
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
    app.dependency_overrides[get_admin_use_cases] = lambda: uc
    with TestClient(app) as client:
        resp = client.get("/api/v2/admin/reports/attendance-trends?periods=2026-01&periods=2026-02")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["periods"]) == 2
    uc.get_attendance_trends.assert_awaited_once_with(["2026-01", "2026-02"])


# ---------------------------------------------------------------------------
# Coach utilization
# ---------------------------------------------------------------------------


def test_coach_utilization_returns_result(analytics_client: TestClient) -> None:
    resp = analytics_client.get("/api/v2/admin/reports/coach-utilization?periods=2026-01")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["coaches"]) == 1
    assert body["coaches"][0]["coach_id"] == "coach-1"
    assert body["total_payout_minor"] == 160000


def test_coach_utilization_multiple_periods(analytics_client: TestClient) -> None:
    uc = SimpleNamespace(
        get_coach_utilization=AsyncMock(
            return_value=CoachUtilizationResult(
                coaches=[
                    CoachUtilizationPoint(
                        coach_id="coach-1",
                        period="2026-01",
                        hours=Decimal("30"),
                        payout_minor=120000,
                        utilization_rate=Decimal("0.7500"),
                    ),
                    CoachUtilizationPoint(
                        coach_id="coach-1",
                        period="2026-02",
                        hours=Decimal("35"),
                        payout_minor=140000,
                        utilization_rate=Decimal("0.8750"),
                    ),
                ],
                periods=["2026-01", "2026-02"],
                total_payout_minor=260000,
            )
        )
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
    app.dependency_overrides[get_admin_use_cases] = lambda: uc
    with TestClient(app) as client:
        resp = client.get("/api/v2/admin/reports/coach-utilization?periods=2026-01&periods=2026-02")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["coaches"]) == 2
    assert body["total_payout_minor"] == 260000
    uc.get_coach_utilization.assert_awaited_once_with(["2026-01", "2026-02"])


# ---------------------------------------------------------------------------
# Auth / persona guards
# ---------------------------------------------------------------------------


def test_analytics_routes_require_admin_persona() -> None:
    """Non-admin persona (coach) must receive 404 (persona not found)."""
    client = _make_client(roles=("coach",))
    resp = client.get("/api/v2/admin/reports/enrollment-funnel")
    assert resp.status_code == 404


def test_analytics_routes_require_auth() -> None:
    """Unauthenticated request must receive 401."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    # No dependency override for get_auth_claims → real guard raises 401
    app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(
        get_enrollment_funnel=AsyncMock(return_value=_FUNNEL_RESULT),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v2/admin/reports/enrollment-funnel")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_attendance_trends_invalid_period_format_returns_422(
    analytics_client: TestClient,
) -> None:
    resp = analytics_client.get("/api/v2/admin/reports/attendance-trends?periods=January-2026")
    assert resp.status_code == 422


def test_attendance_trends_invalid_month_returns_422(analytics_client: TestClient) -> None:
    resp = analytics_client.get("/api/v2/admin/reports/attendance-trends?periods=2026-13")
    assert resp.status_code == 422
