"""Preview of the autopay date-change notice (L8 billing calendar, Nacha notice).

Owner decision: build the template and a preview only. NOTHING here sends: no
sender is wired in, no job, no outbox event, no send use case. The admin reads
the rendered email and the list of families it is meant for, and sends it
through their own channel.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend.v2.composition.email_adapters import render_ach_schedule_notice
from backend.v2.contexts.billing.application.autopay_eligibility import AUTOPAY_ACTIVE_STATUS
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.academy_url import academy_frontend_url


def build_ach_notice_preview(
    db: Any, *, academies: Any, users: Any, frontend_url: str | None
) -> Callable[[str | None], Awaitable[dict[str, Any] | None]]:
    async def preview(parent_id: str | None) -> dict[str, Any] | None:
        """``{subject, html, recipients}`` for ``parent_id`` (the first autopay
        family when omitted); None when no charge-day change is set up, or that
        parent is not on autopay in this academy."""
        academy_id = current_academy_id()
        settings = await MongoBillingSettingsRepository(db).get()
        change = settings.schedule_change
        offset = (change or settings).autopay_charge_offset_days
        if offset is None:
            return None  # autopay still charges on the due date: nothing to announce
        recipients = await _autopay_recipients(db, academy_id, users)
        target = next(
            (r for r in recipients if parent_id is None or r["parent_id"] == parent_id), None
        )
        if parent_id is not None and target is None:
            return None
        academy_doc = await academies.find_by_id(academy_id)
        base = academy_frontend_url(
            frontend_url=frontend_url,
            academy_slug=str((academy_doc or {}).get("slug") or "") or None,
        )
        subject, html = await render_ach_schedule_notice(
            academies=academies,
            parent_name=target["name"] if target else None,
            effective_from=change.effective_from if change else None,
            charge_day=settings.billing_day + offset,
            on_invoice_day=offset == 0,
            manage_url=f"{base}/parent/payments" if base else None,
        )
        return {"subject": subject, "html": html, "recipients": recipients}

    return preview


async def _autopay_recipients(db: Any, academy_id: str, users: Any) -> list[dict[str, Any]]:
    """Every family with an enrollment on active autopay, with the stored method."""
    parent_ids = sorted(
        {
            str(doc.get("parent_id") or doc.get("parent_user_id") or "")
            async for doc in db["student_billing_enrollments"].find(
                {"academy_id": academy_id, "autopay_enrollment_status": AUTOPAY_ACTIVE_STATUS},
                {"parent_id": 1, "parent_user_id": 1},
            )
        }
        - {""}
    )
    customers = {
        str(doc["parent_id"]): doc
        async for doc in db["parent_billing_customers"].find(
            {"academy_id": academy_id, "parent_id": {"$in": parent_ids}}
        )
    }
    out: list[dict[str, Any]] = []
    for pid in parent_ids:
        user = await users.get_by_id(pid)
        label, last4 = MongoParentBillingCustomerRepository.display_payment_method(
            customers.get(pid) or {}
        )
        out.append(
            {
                "parent_id": pid,
                "name": str(getattr(user, "display_name", "") or "") or None,
                "payment_method": " ".join(p for p in (label, last4 and f"ending {last4}") if p)
                or None,
            }
        )
    return sorted(out, key=lambda r: ((r["name"] or "").lower(), r["parent_id"]))
