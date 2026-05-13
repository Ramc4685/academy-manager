"""Email via Resend — welcome, receipt, reminder."""
import os
import asyncio
import logging
import resend
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from bson import ObjectId

from auth import require_roles, log_audit
from db import get_db

router = APIRouter()
log = logging.getLogger(__name__)


def _configured() -> bool:
    key = os.environ.get("RESEND_API_KEY", "")
    return bool(key and key.startswith("re_"))


def _send_sync(to: str, subject: str, html: str) -> dict:
    if not _configured():
        log.warning("Resend not configured — would have emailed %s: %s", to, subject)
        return {"id": "skipped"}
    resend.api_key = os.environ["RESEND_API_KEY"]
    return resend.Emails.send({
        "from": os.environ.get("SENDER_EMAIL", "onboarding@resend.dev"),
        "to": [to],
        "subject": subject,
        "html": html,
    })


async def send_email(to: str, subject: str, html: str) -> dict:
    try:
        return await asyncio.to_thread(_send_sync, to, subject, html)
    except Exception as e:
        log.error("Email send failed: %s", e)
        return {"error": str(e)}


def _wrap(content: str) -> str:
    return f"""<!doctype html><html><body style="background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:24px;color:#0f172a;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
<tr><td style="padding:20px 24px;background:#0f172a;color:#fff;">
<div style="display:flex;align-items:center;gap:12px;">
<div style="background:#facc15;color:#0f172a;width:40px;height:40px;border-radius:8px;display:inline-block;text-align:center;line-height:40px;font-weight:800;">B</div>
<div><div style="font-weight:700;font-size:18px;">BLno Badminton Academy</div></div>
</div></td></tr>
<tr><td style="padding:32px 24px;font-size:15px;line-height:1.6;">
{content}
</td></tr>
<tr><td style="padding:16px 24px;background:#f8fafc;color:#64748b;font-size:12px;text-align:center;border-top:1px solid #e2e8f0;">
BLno Badminton Academy · You're receiving this because you registered at our academy.
</td></tr>
</table></body></html>"""


# -------- Admin/manual triggers --------
class TestEmailIn(BaseModel):
    to: EmailStr


@router.post("/email/test")
async def test_email(body: TestEmailIn, admin=Depends(require_roles("admin"))):
    result = await send_email(
        body.to,
        "✅ BLno Academy — Email is working",
        _wrap("<p>This is a test email from your Badminton Academy Manager.</p>"
              "<p>If you can read this, Resend is wired correctly. 🏸</p>"),
    )
    await log_audit(admin, "email_test", "email", body.to, str(result))
    return {"ok": True, "result": result}


class SendRemindersIn(BaseModel):
    parent_ids: Optional[List[str]] = None  # if None, sends to ALL with dues


@router.post("/email/send-dues-reminders")
async def send_dues_reminders(body: SendRemindersIn, admin=Depends(require_roles("admin"))):
    """Email all parents currently in /dues-followup. Mirrors the WhatsApp logic."""
    db = get_db()
    pending = await db.payments.find({"status": "pending", "is_deleted": {"$ne": True}}).to_list(5000)
    by_parent: dict = {}
    for p in pending:
        pid = p.get("parent_user_id")
        if not pid:
            continue
        if body.parent_ids and pid not in body.parent_ids:
            continue
        by_parent.setdefault(pid, []).append(p)

    settings = await db.academy_settings.find_one({"_id": "singleton"}) or {}
    zelle = settings.get("zelle_handle", "the academy")
    sent = 0
    for pid, items in by_parent.items():
        parent = await db.users.find_one({"_id": ObjectId(pid)})
        if not parent or not parent.get("email"):
            continue
        total = sum(float(p.get("final_amount", 0)) for p in items)
        # Resolve kids
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
        await send_email(parent["email"], "Payment reminder — BLno Badminton Academy", html)
        sent += 1
    await log_audit(admin, "email_reminders", "email", "bulk", f"sent={sent}")
    return {"sent": sent}


@router.post("/email/welcome/{parent_id}")
async def email_welcome(parent_id: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    parent = await db.users.find_one({"_id": ObjectId(parent_id)})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    html = _wrap(
        f"<h2 style='margin:0 0 12px 0;'>Welcome, {parent.get('name')}!</h2>"
        f"<p>Your account is active. Log in any time to:</p>"
        f"<ul><li>View your child's class schedule</li>"
        f"<li>Pay monthly fees by card or Zelle</li>"
        f"<li>See attendance and coach progress notes</li>"
        f"<li>Message your coach</li></ul>"
        f"<p>Login email: <strong>{parent['email']}</strong></p>"
        f"<p>Happy playing! 🏸</p>"
    )
    res = await send_email(parent["email"], "Welcome to BLno Badminton Academy", html)
    await log_audit(admin, "email_welcome", "email", parent_id, str(res))
    return {"ok": True}
