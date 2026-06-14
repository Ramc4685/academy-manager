"""Admin month-scoped payroll routes (GET/POST /admin/payroll/{month}/...)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminMonthlyPayrollRow,
    AdminMonthlyPayrollView,
    BulkPayrollResultView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.payroll"])


def _month_window(month: str) -> tuple[datetime, datetime]:
    try:
        year_s, mon_s = month.split("-")
        year, mon = int(year_s), int(mon_s)
        if not 1 <= mon <= 12:
            raise ValueError
        start = datetime(year, mon, 1, tzinfo=UTC)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM") from exc
    end = datetime(year + (1 if mon == 12 else 0), (mon % 12) + 1, 1, tzinfo=UTC)
    return start, end


@router.get("/payroll/{month}", response_model=AdminMonthlyPayrollView)
async def get_monthly_payroll(
    month: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMonthlyPayrollView:
    start, end = _month_window(month)
    uc = use_cases.list_monthly_payroll
    if uc is None:
        raise HTTPException(status_code=503, detail="Monthly payroll not configured")
    rows = await uc.execute(academy_id=claims.academy_id, period_start=start, period_end=end)
    view_rows = [
        AdminMonthlyPayrollRow(
            coach_id=r.coach_id,
            session_count=r.session_count,
            total_amount_cents=r.total_minor,
            currency=r.currency,
            status=r.status,
            period_id=r.period_id,
        )
        for r in rows
    ]
    return AdminMonthlyPayrollView(
        month=month,
        period_start=start,
        period_end=end,
        rows=view_rows,
        total_amount_cents=sum(r.total_amount_cents for r in view_rows),
    )


@router.post("/payroll/{month}/generate", response_model=BulkPayrollResultView)
async def bulk_generate_payroll(
    month: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BulkPayrollResultView:
    start, end = _month_window(month)
    uc = use_cases.bulk_generate_payroll
    if uc is None:
        raise HTTPException(status_code=503, detail="Bulk generate not configured")
    result = await uc.execute(academy_id=claims.academy_id, period_start=start, period_end=end)
    return BulkPayrollResultView(month=month, generated=result.generated, skipped=result.skipped)


@router.post("/payroll/{month}/recompute", response_model=BulkPayrollResultView)
async def bulk_recompute_payroll(
    month: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BulkPayrollResultView:
    start, end = _month_window(month)
    uc = use_cases.bulk_recompute_payroll
    if uc is None:
        raise HTTPException(status_code=503, detail="Bulk recompute not configured")
    result = await uc.execute(
        academy_id=claims.academy_id,
        period_start=start,
        period_end=end,
        actor_id=claims.user_id,
    )
    return BulkPayrollResultView(month=month, recomputed=result.recomputed, skipped=result.skipped)


@router.get("/payroll/{month}/export")
async def export_monthly_payroll_xlsx(
    month: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
):
    """Download all payout periods for a month as an Excel workbook."""
    import io

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    repo = use_cases.payout_periods
    if repo is None:
        raise HTTPException(status_code=503, detail="Payout periods not configured")
    start, end = _month_window(month)
    periods = await repo.list_for_window(
        academy_id=claims.academy_id, period_start=start, period_end=end
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "Payroll"
    ws.append(["Coach Payroll", month])
    ws.append([])
    grand_total = 0
    for period in periods:
        ws.append([f"Coach: {period.coach_id}", f"Status: {period.status}"])
        ws.append(["Occurrence", "Role", "Pay"])
        for line in period.lines:
            ws.append(
                [
                    line.occurrence_id,
                    "Replacement" if line.basis == "substitute" else "Scheduled",
                    line.amount_minor / 100,
                ]
            )
        ws.append(["", "Subtotal", period.total_minor / 100])
        grand_total += period.total_minor
        ws.append([])
    ws.append(["", "Grand total", grand_total / 100])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="payroll-{month}.xlsx"'},
    )
