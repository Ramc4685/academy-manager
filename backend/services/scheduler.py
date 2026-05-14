"""APScheduler wiring — registers cron jobs at app startup."""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from services.billing_jobs import (
    generate_monthly_invoices,
    send_dues_reminders,
    next_period_yyyy_mm,
)

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Tunable via env, but sensible defaults for an academy in the US.
TZ = os.environ.get("SCHEDULER_TZ", "UTC")
INVOICE_DAY = int(os.environ.get("SCHEDULER_INVOICE_DAY", "1"))    # 1st of month
INVOICE_HOUR = int(os.environ.get("SCHEDULER_INVOICE_HOUR", "9"))   # 09:00
REMINDER_DAY = int(os.environ.get("SCHEDULER_REMINDER_DAY", "5"))  # 5th of month
REMINDER_HOUR = int(os.environ.get("SCHEDULER_REMINDER_HOUR", "9"))


async def _invoice_cron():
    period = next_period_yyyy_mm()
    log.info("[cron] generate-monthly invoices for %s", period)
    try:
        await generate_monthly_invoices(period, actor="cron")
    except Exception:
        log.exception("monthly invoice job failed")


async def _reminder_cron():
    log.info("[cron] dues reminders")
    try:
        await send_dues_reminders(actor="cron")
    except Exception:
        log.exception("dues reminder job failed")


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler:
        return _scheduler
    sch = AsyncIOScheduler(timezone=TZ)
    sch.add_job(
        _invoice_cron,
        CronTrigger(day=INVOICE_DAY, hour=INVOICE_HOUR, minute=0),
        id="monthly_invoices",
        replace_existing=True,
    )
    sch.add_job(
        _reminder_cron,
        CronTrigger(day=REMINDER_DAY, hour=REMINDER_HOUR, minute=0),
        id="dues_reminders",
        replace_existing=True,
    )
    sch.start()
    _scheduler = sch
    log.info("Scheduler started — invoice cron day=%s hour=%s tz=%s; reminder cron day=%s hour=%s",
             INVOICE_DAY, INVOICE_HOUR, TZ, REMINDER_DAY, REMINDER_HOUR)
    return sch


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_status() -> dict:
    if not _scheduler:
        return {"running": False, "jobs": []}
    jobs = []
    for j in _scheduler.get_jobs():
        jobs.append({
            "id": j.id,
            "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
            "trigger": str(j.trigger),
        })
    return {
        "running": _scheduler.running,
        "timezone": TZ,
        "now": datetime.now(timezone.utc).isoformat(),
        "jobs": jobs,
    }
