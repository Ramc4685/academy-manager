"""Parent messages inbox over the shared comms store (UIM13).

Lists the parent's DMs + academy announcements, marks a message read, and
(D-18) lets a parent write to the academy inbox: a thread every admin can see
and answer. The thread is always the caller's own; no id comes from the body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ParentMarkMessageReadResponse,
    ParentMessagesResponse,
    ParentMessageView,
    ParentSendMessageRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.comms import AcademyInboxRateLimited, Message
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


@router.post("/messages", response_model=ParentMessageView, status_code=status.HTTP_201_CREATED)
async def send_message_to_academy(
    payload: ParentSendMessageRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentMessageView:
    """Open or continue this family's thread with the academy (D-18).

    Admins get one email per family per hour, without the message text.
    """
    if use_cases.send_academy_message is None:
        raise HTTPException(status_code=503, detail="Messages are not configured")
    try:
        m = await use_cases.send_academy_message(parent_id=claims.user_id, body=payload.body)
    except AcademyInboxRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many messages in a short time. Please wait a little, or call the academy.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    return _view(m, claims.user_id)


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
        # What the parent sent is never unread to them (no header dot for it).
        read=m.sender_id == user_id or user_id in m.read_by,
        scope_label=m.scope_label,
        urgency=m.urgency,
        # A parent sees the academy's name on a reply, never which staff
        # member wrote it (D-18); announcements keep their author.
        author_display_name=None if m.kind == "dm" else m.author_display_name,
        mine=m.sender_id == user_id,
    )
