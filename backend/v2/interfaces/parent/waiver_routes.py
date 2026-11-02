"""Parent waiver read and acceptance routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

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
