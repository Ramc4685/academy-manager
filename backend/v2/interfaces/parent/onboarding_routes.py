"""Parent onboarding routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    PatchApplicationCommand,
    StartApplicationCommand,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ApplicationView,
    ChildProfileView,
    ParentProfileView,
    PatchApplicationRequest,
    RegistrationWaiverItemView,
    RegistrationWaiverView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.onboarding"])


async def _class_first(use_cases: ParentUseCases) -> bool:
    get_waivers = getattr(use_cases, "get_registration_waivers", None)
    if not get_waivers:
        return False
    _waivers, class_first = await get_waivers(None)
    return bool(class_first)


def _view(app, *, class_first: bool = False) -> ApplicationView:
    return ApplicationView(
        application_id=app.application_id,
        status=app.status,
        parent_profile=ParentProfileView(**app.parent_profile.model_dump()),
        child_profile=ChildProfileView(**app.child_profile.model_dump()),
        selected_session_id=app.selected_session_id,
        waiver_accepted=app.waiver_acceptance is not None,
        waiver_class_first=class_first,
        expires_at=app.expires_at,
    )


@router.get(
    "/onboarding/waiver",
    response_model=RegistrationWaiverView,
    summary="Get the active registration waiver content for the current tenant",
)
async def get_registration_waiver(
    session_id: str | None = Query(default=None, max_length=128),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> RegistrationWaiverView:
    if use_cases.get_registration_waivers:
        waivers, class_first = await use_cases.get_registration_waivers(session_id)
        if not waivers:
            return RegistrationWaiverView(configured=False, class_first=class_first)
        first = waivers[0]
        return RegistrationWaiverView(
            configured=True,
            version=first.version,
            body=first.text,
            class_first=class_first,
            waivers=[
                RegistrationWaiverItemView(
                    waiver_template_id=waiver.waiver_id,
                    title=waiver.title,
                    version=waiver.version,
                    body=waiver.text,
                )
                for waiver in waivers
            ],
        )
    return RegistrationWaiverView(configured=False)


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
    return _view(app, class_first=await _class_first(use_cases))


@router.patch(
    "/onboarding/{application_id}",
    response_model=ApplicationView,
    summary="Patch an in-progress onboarding application",
)
async def patch(
    application_id: str,
    body: PatchApplicationRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ApplicationView:
    app = await use_cases.patch_application.execute(
        PatchApplicationCommand(
            application_id=application_id,
            caller_user_id=claims.user_id,
            parent_profile=body.parent_profile.model_dump() if body.parent_profile else None,
            child_profile=body.child_profile.model_dump() if body.child_profile else None,
            selected_session_id=body.selected_session_id,
            accept_waiver=body.accept_waiver,
        )
    )
    return _view(app, class_first=await _class_first(use_cases))


@router.get(
    "/onboarding/{application_id}/status",
    response_model=ApplicationView,
    summary="Poll application status (used by parent checkout-return page)",
)
async def status_route(
    application_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ApplicationView:
    app = await use_cases.get_application_status.execute(
        application_id, caller_user_id=claims.user_id
    )
    return _view(app, class_first=await _class_first(use_cases))
