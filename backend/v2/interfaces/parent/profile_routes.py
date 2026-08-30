"""GET/PATCH /api/v2/parent/profile — self-service profile for parents.

Fills the gap tracked in issue #380: registration never asked for most of
what the system can store (emergency contact, medical notes) and DOB was
only soft-required, so existing families are often incomplete with no
parent-facing way to fix it. This is the first parent write path in the
codebase — every write below is ownership-checked before anything is
persisted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ParentSelfProfileResponse,
    UpdateParentChildRequest,
    UpdateParentProfileRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.profile"])


@router.get(
    "/profile",
    response_model=ParentSelfProfileResponse,
    summary="Get the current parent's profile, children, and completeness gaps",
)
async def get_profile(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentSelfProfileResponse:
    profile = await use_cases.get_parent_profile(claims.user_id)  # type: ignore[operator]
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return ParentSelfProfileResponse(**profile)


@router.patch(
    "/profile",
    response_model=ParentSelfProfileResponse,
    summary="Update the current parent's display name and/or phone",
)
async def update_profile(
    body: UpdateParentProfileRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentSelfProfileResponse:
    profile = await use_cases.update_parent_profile(  # type: ignore[operator]
        claims.user_id, body
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return ParentSelfProfileResponse(**profile)


@router.post(
    "/profile/confirm-email",
    response_model=ParentSelfProfileResponse,
    summary="Confirm the parent's login email is correct (email itself is not editable here)",
)
async def confirm_email(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentSelfProfileResponse:
    profile = await use_cases.confirm_parent_email(claims.user_id)  # type: ignore[operator]
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return ParentSelfProfileResponse(**profile)


@router.patch(
    "/children/{student_id}",
    response_model=ParentSelfProfileResponse,
    summary="Update a child's DOB, emergency contact, or medical notes",
)
async def update_child(
    student_id: str,
    body: UpdateParentChildRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentSelfProfileResponse:
    profile = await use_cases.update_parent_child(  # type: ignore[operator]
        claims.user_id, student_id, body
    )
    if profile is None:
        # Covers "no such student" and "not this parent's child" alike — never
        # distinguish the two, matching _verify_child_ownership elsewhere in
        # the parent BFF (progress_skill_routes.py). Confirming existence
        # either way is a cross-tenant information leak we don't need to risk.
        raise HTTPException(status_code=404, detail="Student not found")
    return ParentSelfProfileResponse(**profile)
