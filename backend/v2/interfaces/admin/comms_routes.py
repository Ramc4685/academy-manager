"""Admin comms routes — broadcast + DM + inbox."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminMessageList,
    AdminMessageView,
    BroadcastRequest,
    DMRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.comms"])


@router.get("/messages", response_model=AdminMessageList)
async def list_messages(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMessageList:
    msgs = await use_cases.comms.list_for(claims.user_id)
    return AdminMessageList(
        messages=[
            AdminMessageView(
                message_id=m.message_id,
                kind=m.kind,
                sender_id=m.sender_id,
                recipient_id=m.recipient_id,
                body=m.body,
                created_at=m.created_at,
            )
            for m in msgs
        ]
    )


@router.post("/messages/broadcast", response_model=AdminMessageView)
async def broadcast(
    body: BroadcastRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMessageView:
    m = await use_cases.comms.send_broadcast(sender_id=claims.user_id, body=body.body)
    return AdminMessageView(
        message_id=m.message_id,
        kind=m.kind,
        sender_id=m.sender_id,
        recipient_id=m.recipient_id,
        body=m.body,
        created_at=m.created_at,
    )


@router.post("/messages/dm", response_model=AdminMessageView)
async def dm(
    body: DMRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMessageView:
    m = await use_cases.comms.send_dm(
        sender_id=claims.user_id,
        sender_persona="admin",
        recipient_id=body.recipient_id,
        body=body.body,
    )
    return AdminMessageView(
        message_id=m.message_id,
        kind=m.kind,
        sender_id=m.sender_id,
        recipient_id=m.recipient_id,
        body=m.body,
        created_at=m.created_at,
    )
