"""Admin dues reminder route.

``GET /admin/dues-followup`` was deleted with the Dues page (spec §6). The
composition closure ``list_dues_followup`` stays: the dashboard attention-card
builder reads it directly, and it is where the WhatsApp deep link and reminder
text are composed. Only the HTTP route went.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    SendDuesRemindersCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    SendDuesRemindersRequest,
    SendDuesRemindersResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.dues"])


@router.post("/dues-reminders", response_model=SendDuesRemindersResponse)
async def send_dues_reminders(
    body: SendDuesRemindersRequest | None = None,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SendDuesRemindersResponse:
    result = await use_cases.send_dues_reminders.execute(
        SendDuesRemindersCommand(parent_ids=(body.parent_ids if body else None))
    )
    return SendDuesRemindersResponse(**result)
