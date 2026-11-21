"""Admin comms routes — broadcast + DM + inbox + email campaigns + coach digest +
delivery problems."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.v2.contexts.communications.application.errors import (
    AcademyAudience,
    AudienceChangedError,
    DuplicateCampaignError,
    EmptyAudienceError,
    InvalidAudienceError,
    SessionAudience,
    SessionsAudience,
)
from backend.v2.contexts.communications.application.use_cases.send_campaign import (
    SendCampaignCommand,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_digest_test import (
    CoachDigestTargetNotFound,
    SendCoachDigestTestCommand,
)
from backend.v2.interfaces.admin.academy_clock import academy_today
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminMarkMessageReadResponse,
    AdminMessageList,
    AdminMessageView,
    BroadcastRequest,
    CampaignPreviewExclusion,
    CampaignPreviewRecipient,
    CampaignPreviewRequest,
    CampaignPreviewResponse,
    CoachDigestLogEntryView,
    CoachDigestLogView,
    CoachDigestTestSendRequest,
    CoachDigestTestSendResponse,
    DMRequest,
    SendCampaignAudience,
    SendCampaignRequest,
    SendCampaignResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.comms import Message
from backend.v2.shared.comms.public_failure import public_failure
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.comms"])


@router.get("/messages", response_model=AdminMessageList)
async def list_messages(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMessageList:
    msgs = await use_cases.comms.list_for(claims.user_id)
    return AdminMessageList(messages=[_message_view(m, claims.user_id) for m in msgs])


@router.post("/messages/{message_id}/read", response_model=AdminMarkMessageReadResponse)
async def mark_message_read(
    message_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMarkMessageReadResponse:
    """Clear the unread marker on one DM (#864).

    The same shape as the parent and coach endpoints, and the same write: the
    store scopes the update to what this viewer may actually see, so an id
    that is not theirs is a silent no-op rather than an existence oracle.
    """
    await use_cases.comms.mark_read_for_admin(message_id, claims.user_id)
    return AdminMarkMessageReadResponse()


@router.post("/messages/broadcast", response_model=AdminMessageView)
async def broadcast(
    body: BroadcastRequest,
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMessageView:
    m = await use_cases.comms.send_broadcast(
        sender_id=claims.user_id,
        body=body.body,
        scope_type=body.scope_type,
        scope_label=body.scope_label,
    )
    if (push := getattr(request.app.state, "message_push", None)) is not None:
        await push.academy_broadcast(m)
    return _message_view(m, claims.user_id)


@router.post("/messages/dm", response_model=AdminMessageView)
async def dm(
    body: DMRequest,
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMessageView:
    m = await use_cases.comms.send_dm(
        sender_id=claims.user_id,
        sender_persona="admin",
        recipient_id=body.recipient_id,
        body=body.body,
    )
    if (push := getattr(request.app.state, "message_push", None)) is not None:
        await push.direct_message(m)
    return _message_view(m, claims.user_id)


def _campaign_audience(
    raw: SendCampaignAudience,
) -> AcademyAudience | SessionAudience | SessionsAudience:
    if raw.type == "session":
        ids = list(dict.fromkeys(s for s in (raw.session_ids or []) if s))
        if not ids and raw.session_id:
            ids = [raw.session_id]
        if not ids:
            raise HTTPException(status_code=400, detail="session_id required for session audience")
        if len(ids) == 1:
            return SessionAudience(session_id=ids[0])
        return SessionsAudience(session_ids=tuple(ids))
    return AcademyAudience(role=raw.role)


@router.post("/campaigns/preview", response_model=CampaignPreviewResponse)
async def preview_email_campaign(
    payload: CampaignPreviewRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> CampaignPreviewResponse:
    """Read-only: resolves the audience the send would reach; emails nobody."""
    if use_cases.send_campaign is None:
        raise HTTPException(status_code=503, detail="Email campaign sending is not configured")
    try:
        preview = await use_cases.send_campaign.preview(_campaign_audience(payload.audience))
    except InvalidAudienceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CampaignPreviewResponse(
        recipient_count=preview.recipient_count,
        family_count=preview.family_count,
        contact_count=preview.contact_count,
        recipients=[
            CampaignPreviewRecipient(
                display_name=r.display_name,
                email=r.email or "",
                is_family_contact=r.is_family_contact,
            )
            for r in preview.recipients
        ],
        exclusions=[
            CampaignPreviewExclusion(
                display_name=e.display_name,
                email=e.email,
                reason=e.reason,
                is_family_contact=e.is_family_contact,
            )
            for e in preview.exclusions
        ],
        audience_fingerprint=preview.audience_fingerprint,
    )


@router.post("/campaigns", response_model=SendCampaignResponse, status_code=201)
async def send_email_campaign(
    payload: SendCampaignRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SendCampaignResponse:
    if use_cases.send_campaign is None:
        raise HTTPException(status_code=503, detail="Email campaign sending is not configured")

    audience = _campaign_audience(payload.audience)

    try:
        result = await use_cases.send_campaign.execute(
            SendCampaignCommand(
                academy_id=claims.academy_id,
                sender_id=claims.user_id,
                audience=audience,
                subject=payload.subject,
                body=payload.body,
                idempotency_key=payload.idempotency_key,
                expected_audience_fingerprint=payload.expected_audience_fingerprint,
            )
        )
    except AudienceChangedError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "audience_changed", "message": str(exc)}
        ) from exc
    except (EmptyAudienceError, InvalidAudienceError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateCampaignError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SendCampaignResponse(
        campaign_id=result.campaign_id,
        total_recipients=result.total_recipients,
        sent_count=result.sent_count,
        failed_count=result.failed_count,
        deduplicated=result.deduplicated,
        queued=result.queued,
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
                on_date=payload.on_date or await academy_today(use_cases, claims.academy_id),
            )
        )
    except CoachDigestTargetNotFound as exc:
        raise HTTPException(status_code=404, detail="Coach not found") from exc

    return CoachDigestTestSendResponse(
        status=result.status,
        coach_id=result.coach_id,
        email=result.email,
        # A failure detail can be a raw suppression reason from the shared list.
        detail=(
            public_failure(result.detail, "email_delivery_failed")
            if result.status == "failed"
            else result.detail
        ),
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
                failed_reason=(
                    public_failure(row.failed_reason, "email_delivery_failed")
                    if row.failed_reason
                    else None
                ),
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


class FailedDeliveryView(BaseModel):
    delivery_id: str
    recipient_email: str | None
    #: A safe code (``email_delivery_failed``), never provider text.
    failed_reason: str


class DeliveryProblemsView(BaseModel):
    #: This academy's people whose address is not receiving email. No reason or
    #: date: the suppression list is shared, so either could describe another
    #: academy's mail.
    suppressed_emails: list[str]
    failed: list[FailedDeliveryView]


@router.get("/comms/delivery-problems", response_model=DeliveryProblemsView)
async def get_delivery_problems(
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
) -> DeliveryProblemsView:
    """Suppressed addresses and failed campaign sends for this academy's own
    people only. Read-only: clearing an address stays a platform action (L11)."""
    result = await request.app.state.delivery_problems.execute()
    return DeliveryProblemsView(
        suppressed_emails=result.suppressed_emails,
        failed=[FailedDeliveryView(**asdict(d)) for d in result.failed],
    )


def _message_view(m: Message, viewer_id: str) -> AdminMessageView:
    # An inbound DM is one this admin did not send. It is the only thing that
    # can be unread, and the only thing whose `recipient_id` is the admin
    # themselves — so the thread it belongs to is keyed by its *sender*.
    inbound = m.kind == "dm" and m.sender_id != viewer_id
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
        counterparty_id=(
            None if m.kind == "announcement" else (m.sender_id if inbound else m.recipient_id)
        ),
        is_read=(not inbound) or viewer_id in m.read_by,
    )
