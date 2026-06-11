"""Admin comms routes — broadcast + DM + inbox + email campaigns."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.contexts.communications.application.errors import (
    AcademyAudience,
    EmptyAudienceError,
    SessionAudience,
)
from backend.v2.contexts.communications.application.use_cases.send_campaign import (
    SendCampaignCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminMessageList,
    AdminMessageView,
    BroadcastRequest,
    DMRequest,
    SendCampaignRequest,
    SendCampaignResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.comms import Message
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.comms"])


@router.get("/messages", response_model=AdminMessageList)
async def list_messages(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMessageList:
    msgs = await use_cases.comms.list_for(claims.user_id)
    return AdminMessageList(messages=[_message_view(m) for m in msgs])


@router.post("/messages/broadcast", response_model=AdminMessageView)
async def broadcast(
    body: BroadcastRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMessageView:
    m = await use_cases.comms.send_broadcast(
        sender_id=claims.user_id,
        body=body.body,
        scope_type=body.scope_type,
        scope_label=body.scope_label,
    )
    return _message_view(m)


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
    return _message_view(m)


@router.post("/campaigns", response_model=SendCampaignResponse, status_code=201)
async def send_email_campaign(
    payload: SendCampaignRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SendCampaignResponse:
    if use_cases.send_campaign is None:
        raise HTTPException(status_code=503, detail="Email campaign sending is not configured")

    if payload.audience.type == "session":
        if not payload.audience.session_id:
            raise HTTPException(status_code=400, detail="session_id required for session audience")
        audience = SessionAudience(session_id=payload.audience.session_id)
    else:
        audience = AcademyAudience(role=payload.audience.role)

    try:
        result = await use_cases.send_campaign.execute(
            SendCampaignCommand(
                academy_id=claims.academy_id,
                sender_id=claims.user_id,
                audience=audience,
                subject=payload.subject,
                body=payload.body,
            )
        )
    except EmptyAudienceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SendCampaignResponse(
        campaign_id=result.campaign_id,
        total_recipients=result.total_recipients,
        sent_count=result.sent_count,
        failed_count=result.failed_count,
    )


def _message_view(m: Message) -> AdminMessageView:
    return AdminMessageView(
        message_id=m.message_id,
        kind=m.kind,
        sender_id=m.sender_id,
        recipient_id=m.recipient_id,
        body=m.body,
        created_at=m.created_at,
        sent_at=m.created_at,
        is_broadcast=m.kind == "announcement",
        scope_type=m.scope_type or ("academy" if m.kind == "announcement" else "direct"),
        scope_label=(
            m.scope_label
            or ("Whole academy announcement" if m.kind == "announcement" else "Direct message")
        ),
        recipient_count=m.recipient_count,
        delivery_status=m.delivery_status or "recorded",
    )
