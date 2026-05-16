"""Parent onboarding routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    PatchApplicationCommand,
    StartApplicationCommand,
)
from backend.v2.contexts.onboarding.domain.models import ChildProfile, ParentProfile
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ApplicationView,
    ChildProfileView,
    ParentProfileView,
    PatchApplicationRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.onboarding"])


def _view(app) -> ApplicationView:
    return ApplicationView(
        application_id=app.application_id,
        status=app.status,
        parent_profile=ParentProfileView(**app.parent_profile.model_dump()),
        child_profile=ChildProfileView(**app.child_profile.model_dump()),
        selected_session_id=app.selected_session_id,
        waiver_accepted=app.waiver_acceptance is not None,
        expires_at=app.expires_at,
    )


@router.post(
    "/onboarding/start",
    response_model=ApplicationView,
    status_code=status.HTTP_200_OK,
    summary="Start (or return existing draft) onboarding application for the signed-in parent",
)
async def start(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ApplicationView:
    app = await use_cases.start_application.execute(
        StartApplicationCommand(
            parent_user_id=claims.user_id,
            parent_email=claims.email,
        )
    )
    return _view(app)


@router.patch(
    "/onboarding/{application_id}",
    response_model=ApplicationView,
    summary="Patch an in-progress onboarding application",
)
async def patch(
    application_id: str,
    body: PatchApplicationRequest,
    _claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ApplicationView:
    app = await use_cases.patch_application.execute(
        PatchApplicationCommand(
            application_id=application_id,
            parent_profile=(
                ParentProfile.model_validate(body.parent_profile.model_dump())
                if body.parent_profile
                else None
            ),
            child_profile=(
                ChildProfile.model_validate(body.child_profile.model_dump())
                if body.child_profile
                else None
            ),
            selected_session_id=body.selected_session_id,
            accept_waiver=body.accept_waiver,
        )
    )
    return _view(app)


@router.get(
    "/onboarding/{application_id}/status",
    response_model=ApplicationView,
    summary="Poll application status (used by parent checkout-return page)",
)
async def status_route(
    application_id: str,
    _claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ApplicationView:
    app = await use_cases.get_application_status.execute(application_id)
    return _view(app)
