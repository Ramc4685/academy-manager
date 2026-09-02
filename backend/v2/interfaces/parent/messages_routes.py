"""Parent messages inbox — read-only over the shared comms store (UIM13).

Messages are already persisted per-recipient by admin's broadcast/DM
endpoints (`backend/v2/shared/comms/messages.py`). This module only adds
the parent-side read surface: list the parent's DMs + academy
announcements, and mark a message read.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ParentMarkMessageReadResponse,
    ParentMessagesResponse,
    ParentMessageView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.comms import Message
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.messages"])


@router.get("/messages", response_model=ParentMessagesResponse)
async def list_messages(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentMessagesResponse:
    if use_cases.list_messages is None:
        raise HTTPException(status_code=503, detail="Messages are not configured")
    msgs = await use_cases.list_messages(claims.user_id)
    return ParentMessagesResponse(
        messages=[_view(m, claims.user_id) for m in msgs],
    )


@router.post("/messages/{message_id}/read", response_model=ParentMarkMessageReadResponse)
async def mark_message_read(
    message_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentMarkMessageReadResponse:
    if use_cases.mark_message_read is None:
        raise HTTPException(status_code=503, detail="Messages are not configured")
    await use_cases.mark_message_read(message_id, claims.user_id)
    return ParentMarkMessageReadResponse()


def _view(m: Message, user_id: str) -> ParentMessageView:
    return ParentMessageView(
        message_id=m.message_id,
        kind=m.kind,
        sender_persona=m.sender_persona,
        body=m.body,
        created_at=m.created_at,
        read=user_id in m.read_by,
        scope_label=m.scope_label,
        urgency=m.urgency,
        author_display_name=m.author_display_name,
    )
