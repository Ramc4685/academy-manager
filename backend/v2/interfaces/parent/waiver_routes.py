"""Parent waiver read and acceptance routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.contexts.onboarding.application.use_cases.ai_video_consent import (
    ParentAiVideoConsent,
    ParentAiVideoConsentView,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ParentSignedWaiverView,
    ParentWaiverAcceptRequest,
    ParentWaiverCurrentView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import request_ip, require_persona

router = APIRouter(tags=["parent.waivers"])


@router.get("/waivers/current", response_model=ParentWaiverCurrentView)
async def current_parent_waiver(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentWaiverCurrentView:
    result = await use_cases.get_parent_waiver_requirement.execute(parent_id=claims.user_id)
    return ParentWaiverCurrentView(**result.model_dump())


@router.post("/waivers/accept", response_model=ParentWaiverCurrentView)
async def accept_parent_waiver(
    body: ParentWaiverAcceptRequest,
    request: Request,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentWaiverCurrentView:
    result = await use_cases.accept_parent_waiver.execute(
        parent_id=claims.user_id,
        signer_name=body.signer_name,
        signer_email=claims.email,
        ip_address=request_ip(request),
        user_agent=request.headers.get("user-agent"),
        consent=body.consent,
        student_ids=body.student_ids,
        initials=body.initials,
    )
    return ParentWaiverCurrentView(**result.model_dump())


@router.get("/waivers/signatures/{signature_id}", response_model=ParentSignedWaiverView)
async def parent_signed_waiver(
    signature_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentSignedWaiverView:
    copy = await use_cases.get_parent_signed_waiver.execute(
        parent_id=claims.user_id, waiver_signature_id=signature_id
    )
    return ParentSignedWaiverView(**copy.model_dump())


# --- Per-child AI/video consent (Phase 3 E1): stored and unused ---------------


class ParentAiVideoConsentGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The version of the text the parent read; a stale page is refused (409).
    text_version: str = Field(min_length=1, max_length=128)
    consent: bool


def _ai_video_consent(use_cases: ParentUseCases) -> ParentAiVideoConsent:
    if use_cases.ai_video_consent is None:
        raise HTTPException(status_code=404, detail="Not found")
    return use_cases.ai_video_consent


@router.get("/waivers/ai-video-consent", response_model=ParentAiVideoConsentView)
async def parent_ai_video_consent(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentAiVideoConsentView:
    return await _ai_video_consent(use_cases).get(parent_id=claims.user_id)


@router.post(
    "/waivers/ai-video-consent/{student_id}/grant", response_model=ParentAiVideoConsentView
)
async def grant_parent_ai_video_consent(
    student_id: str,
    body: ParentAiVideoConsentGrantRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentAiVideoConsentView:
    return await _ai_video_consent(use_cases).grant(
        parent_id=claims.user_id,
        student_id=student_id,
        text_version=body.text_version,
        consent=body.consent,
        signer_email=claims.email,
    )


@router.post(
    "/waivers/ai-video-consent/{student_id}/revoke", response_model=ParentAiVideoConsentView
)
async def revoke_parent_ai_video_consent(
    student_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentAiVideoConsentView:
    return await _ai_video_consent(use_cases).revoke(
        parent_id=claims.user_id, student_id=student_id
    )
