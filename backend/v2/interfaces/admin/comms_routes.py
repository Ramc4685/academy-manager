"""Admin comms routes — broadcast + DM + inbox + email campaigns + coach digest."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.contexts.communications.application.errors import (
    AcademyAudience,
    EmptyAudienceError,
    SessionAudience,
)
from backend.v2.contexts.communications.application.use_cases.send_campaign import (
    SendCampaignCommand,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_digest_test import (
    CoachDigestTargetNotFound,
    SendCoachDigestTestCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminMessageList,
    AdminMessageView,
    BroadcastRequest,
    CoachDigestLogEntryView,
    CoachDigestLogView,
    CoachDigestTestSendRequest,
    CoachDigestTestSendResponse,
    DMRequest,
    SendCampaignRequest,
    SendCampaignResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.comms import Message
from backend.v2.shared.config import get_settings
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.comms"])


def _scheduler_today() -> date:
    settings = get_settings()
    try:
        scheduler_tz = ZoneInfo(settings.scheduler_tz)
    except ZoneInfoNotFoundError:
        scheduler_tz = UTC
    return datetime.now(UTC).astimezone(scheduler_tz).date()


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


@router.post("/comms/digests/test-send", response_model=CoachDigestTestSendResponse)
async def send_coach_digest_test(
    payload: CoachDigestTestSendRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> CoachDigestTestSendResponse:
    if use_cases.send_coach_digest_test is None:
        raise HTTPException(status_code=503, detail="Coach digest sending is not configured")

    # Target a named coach, or the admin themselves ("self"/omitted).
    raw = (payload.coach_id or "").strip()
    target_user_id = claims.user_id if raw in ("", "self") else raw

    try:
        result = await use_cases.send_coach_digest_test.execute(
            SendCoachDigestTestCommand(
                academy_id=claims.academy_id,
                target_user_id=target_user_id,
                on_date=_scheduler_today(),
            )
        )
    except CoachDigestTargetNotFound as exc:
        raise HTTPException(status_code=404, detail="Coach not found") from exc

    return CoachDigestTestSendResponse(
        status=result.status,
        coach_id=result.coach_id,
        email=result.email,
        detail=result.detail,
    )


@router.get("/comms/digests/log", response_model=CoachDigestLogView)
async def get_coach_digest_log(
    limit: int = 20,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> CoachDigestLogView:
    if use_cases.get_digest_delivery_log is None:
        raise HTTPException(status_code=503, detail="Coach digest log is not configured")

    limit = max(1, min(limit, 100))
    rows = await use_cases.get_digest_delivery_log.execute(claims.academy_id, limit=limit)
    return CoachDigestLogView(
        entries=[
            CoachDigestLogEntryView(
                digest_id=row.digest_id,
                coach_id=row.coach_id,
                coach_email=row.coach_email,
                digest_date=row.digest_date,
                status=str(row.status),
                kind=row.kind,
                sent_at=row.sent_at,
                failed_reason=row.failed_reason,
                created_at=row.created_at,
            )
            for row in rows
        ]
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
