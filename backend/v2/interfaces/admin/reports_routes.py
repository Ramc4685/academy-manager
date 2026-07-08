"""Admin report export routes."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminProjectedIncomeResponse,
    AdminReportsDashboardResponse,
    AdminSessionEconomicsResponse,
    AttendanceTrendsResponse,
    CoachUtilizationResponse,
    EnrollmentFunnelResponse,
    ReportsKpiResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_EXPORT_REPORTS = frozenset({"pending-payments", "revenue", "attendance"})

router = APIRouter(tags=["admin.reports"])


@router.get("/reports/dashboard", response_model=AdminReportsDashboardResponse)
async def get_reports_dashboard(
    period: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")],
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminReportsDashboardResponse:
    month = int(period[5:7])
    if month < 1 or month > 12:
        raise HTTPException(status_code=422, detail="period must be YYYY-MM")
    result = await use_cases.get_reports_dashboard(period)  # type: ignore[attr-defined]
    return AdminReportsDashboardResponse(**result)


@router.get("/reports/session-economics", response_model=AdminSessionEconomicsResponse)
async def get_session_economics(
    period: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")],
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionEconomicsResponse:
    month = int(period[5:7])
    if month < 1 or month > 12:
        raise HTTPException(status_code=422, detail="period must be YYYY-MM")
    if use_cases.get_session_economics is None:
        raise HTTPException(status_code=503, detail="session economics report is unavailable")
    result = await use_cases.get_session_economics(period)  # type: ignore[operator]
    return AdminSessionEconomicsResponse(**result)


@router.get("/reports/projected-income", response_model=AdminProjectedIncomeResponse)
async def get_projected_income(
    period: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")],
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminProjectedIncomeResponse:
    month = int(period[5:7])
    if month < 1 or month > 12:
        raise HTTPException(status_code=422, detail="period must be YYYY-MM")
    if use_cases.get_projected_income is None:
        raise HTTPException(status_code=503, detail="projected income report is unavailable")
    result = await use_cases.get_projected_income(period)  # type: ignore[operator]
    return AdminProjectedIncomeResponse(**result)


@router.get("/reports/kpis", response_model=ReportsKpiResponse)
async def get_reports_kpis(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ReportsKpiResponse:
    result = await use_cases.get_reports_kpis()  # type: ignore[operator]
    return ReportsKpiResponse(**result)


@router.get("/reports/enrollment-funnel", response_model=EnrollmentFunnelResponse)
async def get_enrollment_funnel(
    period: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> EnrollmentFunnelResponse:
    result = await use_cases.get_enrollment_funnel(period)  # type: ignore[operator]
    return EnrollmentFunnelResponse(**result.model_dump())


@router.get("/reports/attendance-trends", response_model=AttendanceTrendsResponse)
async def get_attendance_trends(
    periods: Annotated[list[str], Query(...)],
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AttendanceTrendsResponse:
    invalid = [p for p in periods if not _PERIOD_RE.match(p)]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid period format: {invalid}")
    result = await use_cases.get_attendance_trends(periods)  # type: ignore[operator]
    return AttendanceTrendsResponse(**result.model_dump())


@router.get("/reports/coach-utilization", response_model=CoachUtilizationResponse)
async def get_coach_utilization(
    periods: Annotated[list[str], Query(...)],
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> CoachUtilizationResponse:
    invalid = [p for p in periods if not _PERIOD_RE.match(p)]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid period format: {invalid}")
    result = await use_cases.get_coach_utilization(periods)  # type: ignore[operator]
    return CoachUtilizationResponse(**result.model_dump())


@router.get("/reports/{report_name}.csv")
async def export_report_csv(
    report_name: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> Response:
    if report_name not in _EXPORT_REPORTS:
        raise HTTPException(status_code=404, detail="Report export not found")
    csv_text = await use_cases.export_report_csv(report_name)  # type: ignore[operator]
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{report_name}.csv"'},
    )
