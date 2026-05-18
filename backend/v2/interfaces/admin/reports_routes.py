"""Admin report export routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.reports"])


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
