"""Admin-facing scheduler endpoints: status + on-demand cron triggers."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_roles, log_audit
from services.scheduler import scheduler_status
from services.billing_jobs import (
    generate_monthly_invoices,
    send_dues_reminders,
    next_period_yyyy_mm,
    current_period_yyyy_mm,
)

router = APIRouter()


@router.get("/scheduler/status")
async def get_status(admin=Depends(require_roles("admin"))):
    return scheduler_status()


class RunInvoiceIn(BaseModel):
    period: str | None = None  # YYYY-MM; defaults to next month


@router.post("/scheduler/run-monthly-invoices")
async def run_monthly_invoices(body: RunInvoiceIn, admin=Depends(require_roles("admin"))):
    period = body.period or next_period_yyyy_mm()
    result = await generate_monthly_invoices(period, actor=f"admin:{admin['email']}")
    await log_audit(admin, "manual_run", "scheduler", "monthly_invoices", str(result))
    return result


@router.post("/scheduler/run-dues-reminders")
async def run_dues_reminders(admin=Depends(require_roles("admin"))):
    result = await send_dues_reminders(actor=f"admin:{admin['email']}")
    await log_audit(admin, "manual_run", "scheduler", "dues_reminders", str(result))
    return result


@router.get("/scheduler/next-period")
async def next_period(admin=Depends(require_roles("admin"))):
    return {"next_period": next_period_yyyy_mm(), "current_period": current_period_yyyy_mm()}
