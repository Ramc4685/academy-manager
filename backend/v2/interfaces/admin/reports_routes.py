"""Admin report export routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminReportsDashboardResponse,
    ReportsKpiResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

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


@router.get("/reports/kpis", response_model=ReportsKpiResponse)
async def get_reports_kpis(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ReportsKpiResponse:
    result = await use_cases.get_reports_kpis()  # type: ignore[operator]
    return ReportsKpiResponse(**result)


@router.get("/reports/{report_name}.csv")
async def export_report_csv(
    report_name: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> Response:
    csv_text = await use_cases.export_report_csv(report_name)  # type: ignore[operator]
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{report_name}.csv"'},
    )
