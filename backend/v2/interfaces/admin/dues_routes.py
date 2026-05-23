"""Admin dues follow-up routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    SendDuesRemindersCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    DuesFollowupParentView,
    DuesFollowupResponse,
    SendDuesRemindersRequest,
    SendDuesRemindersResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.dues"])


@router.get("/dues-followup", response_model=DuesFollowupResponse)
async def dues_followup(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> DuesFollowupResponse:
    rows = await use_cases.list_dues_followup()  # type: ignore[operator]
    return DuesFollowupResponse(parents=[DuesFollowupParentView(**row) for row in rows])


@router.post("/dues-reminders", response_model=SendDuesRemindersResponse)
async def send_dues_reminders(
    body: SendDuesRemindersRequest | None = None,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SendDuesRemindersResponse:
    result = await use_cases.send_dues_reminders.execute(  # type: ignore[operator]
        SendDuesRemindersCommand(parent_ids=(body.parent_ids if body else None))
    )
    return SendDuesRemindersResponse(**result)
