"""Reusable monthly billing + dues-reminder jobs callable from APScheduler or HTTP."""
from __future__ import annotations

import os
import asyncio
import logging
from datetime import datetime, timezone
from bson import ObjectId

from db import get_db

log = logging.getLogger(__name__)


def next_period_yyyy_mm(today: datetime | None = None) -> str:
    d = today or datetime.now(timezone.utc)
    year = d.year + (1 if d.month == 12 else 0)
    month = 1 if d.month == 12 else d.month + 1
    return f"{year:04d}-{month:02d}"


def current_period_yyyy_mm(today: datetime | None = None) -> str:
    d = today or datetime.now(timezone.utc)
    return f"{d.year:04d}-{d.month:02d}"


def _invoice_number(prefix: str = "INV") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


async def generate_monthly_invoices(period: str, actor: str = "scheduler") -> dict:
    """Create pending payments for every active enrollment for the given period.
    Mirrors POST /api/payments/generate-monthly exactly so the cron job behaves
    identically to the admin button. Idempotent — never duplicates a (enrollment_id, period)."""
    db = get_db()
    enrollments = await db.enrollments.find({
        "status": "active",
        "is_deleted": {"$ne": True},
        "approval_status": {"$nin": ["pending", "pending_payment"]},
    }).to_list(5000)
    created = 0
    skipped = 0
    skipped_no_charge = 0
    skipped_paused = 0
    skipped_autopay = 0
    for e in enrollments:
        if period in (e.get("skip_periods", []) or []):
            skipped_paused += 1
            continue
        if e.get("payment_mode") == "autopay" and e.get("subscription_status") in {"active", "trialing", "past_due"}:
            skipped_autopay += 1
            continue
        bt = e.get("billing_type", "Standard")
        if bt and bt.lower() != "standard":
            skipped_no_charge += 1
            continue
        existing = await db.payments.find_one({"enrollment_id": str(e["_id"]), "period": period})
        if existing:
            skipped += 1
            continue
        overrides = e.get("session_overrides", {}) or {}
        session_id = overrides.get(period, e["session_id"])
        session = await db.sessions.find_one({"_id": ObjectId(session_id)})
        if not session:
            continue
        price = float(session.get("monthly_price", 0))
        doc = {
            "parent_user_id": e["parent_user_id"],
            "student_id": e["student_id"],
            "enrollment_id": str(e["_id"]),
            "session_id": session_id,
            "period": period,
            "amount": price,
            "discount": 0,
            "final_amount": price,
            "status": "pending",
            "payment_date": None,
            "payment_method": None,
            "marked_by": None,
            "notes": "",
            "invoice_number": _invoice_number(),
            "invoice_created_at": datetime.now(timezone.utc).isoformat(),
            "refunded_amount": 0,
            "refund_status": "none",
            "refunds": [],
            "is_deleted": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.payments.insert_one(doc)
        created += 1

    summary = {
        "period": period,
        "created": created,
        "skipped": skipped,
        "skipped_no_charge": skipped_no_charge,
        "skipped_paused": skipped_paused,
        "skipped_autopay": skipped_autopay,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
    }
    await db.audit_logs.insert_one({
        "user_id": actor,
        "action": "generate",
        "entity": "payment",
        "entity_id": period,
        "note": f"[{actor}] created {created} skipped {skipped} no_charge {skipped_no_charge} paused {skipped_paused} autopay {skipped_autopay}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    log.info("Monthly invoice job %s: %s", period, summary)
    return summary


async def send_dues_reminders(actor: str = "scheduler") -> dict:
    """Email every parent who has at least one pending payment.
    Mirrors POST /api/email/send-dues-reminders without admin context. Safe to call from cron."""
    from routers.email_routes import send_email, _wrap, _delivery_status, _configured, _is_skipped

    db = get_db()
    if not _configured():
        log.warning("Resend not configured — skipping dues reminders")
        return {"sent": 0, "failed": 0, "skipped": 0, "reason": "resend_not_configured"}

    pending = await db.payments.find({"status": "pending", "is_deleted": {"$ne": True}}).to_list(5000)
    by_parent: dict = {}
    for p in pending:
        pid = p.get("parent_user_id")
        if not pid:
            continue
        by_parent.setdefault(pid, []).append(p)

    settings = await db.academy_settings.find_one({"_id": "singleton"}) or {}
    zelle = settings.get("zelle_handle", "the academy")
    sent = failed = skipped = 0
    for pid, items in by_parent.items():
        try:
            parent = await db.users.find_one({"_id": ObjectId(pid)})
        except Exception:
            continue
        if not parent or not parent.get("email"):
            continue
        total = sum(float(p.get("final_amount", 0)) for p in items)
        stu_ids = list({p["student_id"] for p in items if p.get("student_id")})
        kids = []
        async for s in db.students.find({"_id": {"$in": [ObjectId(x) for x in stu_ids]}}):
            kids.append(f"{s['first_name']} {s['last_name']}")
        html = _wrap(
            f"<h2 style='margin:0 0 12px 0;'>Friendly reminder</h2>"
            f"<p>Hi {parent.get('name') or parent['email']},</p>"
            f"<p>You have <strong style='color:#2563eb;'>${total:.0f}</strong> pending for "
            f"<strong>{' & '.join(kids) or 'your child'}</strong>'s badminton training.</p>"
            f"<p>Please send payment via <strong>Zelle to {zelle}</strong>, or log in to pay by card.</p>"
            f"<p>Thank you! 🏸</p>"
        )
        result = await send_email(parent["email"], "Payment reminder — BLno Badminton Academy", html)
        delivered, _ = _delivery_status(result)
        if delivered:
            sent += 1
        elif _is_skipped(result):
            skipped += 1
        else:
            failed += 1

    summary = {
        "sent": sent, "failed": failed, "skipped": skipped,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
    }
    await db.audit_logs.insert_one({
        "user_id": actor,
        "action": "email_reminders",
        "entity": "email",
        "entity_id": "bulk_scheduled",
        "note": f"[{actor}] sent={sent} failed={failed} skipped={skipped}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    log.info("Dues-reminder job: %s", summary)
    return summary


# Wrappers that APScheduler can call (must run inside the running event loop)
def schedule_invoice_job():
    return asyncio.create_task(generate_monthly_invoices(next_period_yyyy_mm(), actor="cron"))


def schedule_dues_reminder_job():
    return asyncio.create_task(send_dues_reminders(actor="cron"))
