"""Admin month-scoped payroll routes (GET/POST /admin/payroll/{month}/...)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminMonthlyPayrollRow,
    AdminMonthlyPayrollView,
    BulkPayrollResultView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner
from backend.v2.shared.time.academy_timezone import resolve_academy_clock_timezone

#: Spreadsheet role per line basis, shared with the period export.
PAYROLL_ROLE_LABELS = {"substitute": "Replacement", "assistant": "Assistant"}

router = APIRouter(tags=["admin.payroll"])


class PayrollSettingsView(BaseModel):
    """How a percent coach's invoiced-tuition base is counted (L7).

    Applies to periods generated or recomputed after a change.
    """

    model_config = ConfigDict(extra="forbid")

    payroll_ach_discount_reduces_base: bool
    payroll_count_checkout_first_month: bool
    payroll_cancelled_class_share: Literal["ran_only", "all_scheduled"]
    payroll_missing_invoices: Literal["block", "pay_zero"]
    #: First month (YYYY-MM) assistants are paid in the app; null = never.
    payroll_assistant_pay_from: str | None = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


@router.get("/payroll-settings", response_model=PayrollSettingsView)
async def get_payroll_settings(
    _claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> PayrollSettingsView:
    uc = use_cases.get_payroll_settings
    if uc is None:
        raise HTTPException(status_code=503, detail="Payroll settings not configured")
    return PayrollSettingsView(**await uc.execute())


@router.put("/payroll-settings", response_model=PayrollSettingsView)
async def update_payroll_settings(
    body: PayrollSettingsView,
    claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> PayrollSettingsView:
    uc = use_cases.update_payroll_settings
    current_uc = use_cases.get_payroll_settings
    if uc is None or current_uc is None:
        raise HTTPException(status_code=503, detail="Payroll settings not configured")
    pay_from = body.payroll_assistant_pay_from
    # Back-dating would re-price closed months; an unchanged older value still saves.
    if pay_from is not None and pay_from != (await current_uc.execute()).get(
        "payroll_assistant_pay_from"
    ):
        zone = await resolve_academy_clock_timezone(
            _academy_timezone_reader(use_cases), claims.academy_id
        )
        this_month = datetime.now(ZoneInfo(zone)).strftime("%Y-%m")
        if pay_from < this_month:
            raise HTTPException(
                status_code=422,
                detail=f"payroll_assistant_pay_from cannot be earlier than {this_month}",
            )
    saved = await uc.execute(
        academy_id=claims.academy_id, actor_id=claims.user_id, values=body.model_dump()
    )
    return PayrollSettingsView(**saved)


def _month_window(month: str, tz: tzinfo = UTC) -> tuple[datetime, datetime]:
    """UTC instants bounding the calendar month in timezone ``tz``.

    Occurrences are stored as UTC instants for academy-local class times, so
    month bucketing must use academy-local month boundaries or a month-end
    evening class rolls into the next month's payroll (#510).
    """
    try:
        year_s, mon_s = month.split("-")
        year, mon = int(year_s), int(mon_s)
        if not 1 <= mon <= 12:
            raise ValueError
        start = datetime(year, mon, 1, tzinfo=tz)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM") from exc
    end = datetime(year + (1 if mon == 12 else 0), (mon % 12) + 1, 1, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


async def _academy_month_window(
    month: str, *, academy_id: str, use_cases: AdminUseCases
) -> tuple[datetime, datetime]:
    """The academy-local month, on the same clock the pay base buckets invoices by."""

    zone = await resolve_academy_clock_timezone(_academy_timezone_reader(use_cases), academy_id)
    return _month_window(month, ZoneInfo(zone))


def _academy_timezone_reader(
    use_cases: AdminUseCases,
) -> Callable[[str], Awaitable[str | None]]:
    async def academy_timezone(aid: str) -> str | None:
        return (await use_cases.get_academy_use_case.execute(aid)).timezone

    return academy_timezone


@router.get("/payroll/{month}", response_model=AdminMonthlyPayrollView)
async def get_monthly_payroll(
    month: str,
    claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMonthlyPayrollView:
    start, end = await _academy_month_window(
        month, academy_id=claims.academy_id, use_cases=use_cases
    )
    uc = use_cases.list_monthly_payroll
    if uc is None:
        raise HTTPException(status_code=503, detail="Monthly payroll not configured")
    rows = await uc.execute(academy_id=claims.academy_id, period_start=start, period_end=end)
    coaches = await use_cases.list_admin_users.execute("coach", academy_id=claims.academy_id)
    coach_names = {user.user_id: user.display_name for user in coaches}
    view_rows = [
        AdminMonthlyPayrollRow(
            coach_id=r.coach_id,
            coach_name=coach_names.get(r.coach_id),
            session_count=r.session_count,
            total_amount_cents=r.total_minor,
            currency=r.currency,
            status=r.status,
            period_id=r.period_id,
            unresolved_unpaid_count=r.unresolved_unpaid_count,
            warning_count=r.warning_count,
            warning_status=r.warning_status,
        )
        for r in rows
    ]
    # D-04: every active coach appears; one who taught nothing is a read-only
    # row (no payslip is created, the UI offers no Generate).
    listed = {r.coach_id for r in view_rows}
    currency = view_rows[0].currency if view_rows else "USD"
    view_rows += [
        AdminMonthlyPayrollRow(
            coach_id=user.user_id,
            coach_name=user.display_name,
            session_count=0,
            total_amount_cents=0,
            currency=currency,
            status="not_generated",
            generatable=False,
        )
        for user in coaches
        if user.status == "active" and user.user_id not in listed
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
    claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BulkPayrollResultView:
    start, end = await _academy_month_window(
        month, academy_id=claims.academy_id, use_cases=use_cases
    )
    uc = use_cases.bulk_generate_payroll
    if uc is None:
        raise HTTPException(status_code=503, detail="Bulk generate not configured")
    result = await uc.execute(academy_id=claims.academy_id, period_start=start, period_end=end)
    return BulkPayrollResultView(month=month, generated=result.generated, skipped=result.skipped)


@router.post("/payroll/{month}/recompute", response_model=BulkPayrollResultView)
async def bulk_recompute_payroll(
    month: str,
    claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BulkPayrollResultView:
    start, end = await _academy_month_window(
        month, academy_id=claims.academy_id, use_cases=use_cases
    )
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
    claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
):
    """Download all payout periods for a month as an Excel workbook."""
    import io

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    repo = use_cases.payout_periods
    if repo is None:
        raise HTTPException(status_code=503, detail="Payout periods not configured")
    start, end = await _academy_month_window(
        month, academy_id=claims.academy_id, use_cases=use_cases
    )
    periods = await repo.list_for_window(
        academy_id=claims.academy_id, period_start=start, period_end=end
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "Payroll"
    ws.append(["Coach Payroll", month])
    ws.append([])
    grand_total = 0
    describe = use_cases.describe_payout_occurrences
    for period in periods:
        warning_descriptions = {}
        if describe is not None and period.payout_warnings:
            warning_descriptions = await describe(  # type: ignore[operator]
                [warning.occurrence_id for warning in period.payout_warnings]
            )
        ws.append(
            [
                f"Coach: {period.coach_id}",
                f"Status: {period.status}",
                f"Warnings: {len(period.payout_warnings)}",
            ]
        )
        ws.append(["Occurrence", "Role", "Pay", "Warning reason", "Date", "Session", "Repair"])
        for line in period.lines:
            ws.append(
                [
                    line.occurrence_id,
                    PAYROLL_ROLE_LABELS.get(line.basis, "Scheduled"),
                    line.amount_minor / 100,
                    "",
                    "",
                    "",
                    "",
                ]
            )
        for warning in period.payout_warnings:
            description = warning_descriptions.get(warning.occurrence_id, {})
            occurred_at = warning.occurred_at or description.get("occurred_at")
            ws.append(
                [
                    warning.occurrence_id,
                    "",
                    0,
                    warning.reason,
                    f"{occurred_at:%Y-%m-%d}" if occurred_at else "",
                    warning.session_title
                    or description.get("session_title")
                    or warning.session_id
                    or description.get("session_id")
                    or "",
                    warning.repair_action,
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
