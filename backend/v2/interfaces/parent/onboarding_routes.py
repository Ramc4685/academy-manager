"""Parent onboarding routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, status

from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    PatchApplicationCommand,
    StartApplicationCommand,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ApplicationView,
    ChildProfileView,
    ParentProfileView,
    ParentRegistrationList,
    ParentRegistrationView,
    PatchApplicationRequest,
    RegistrationWaiverItemView,
    RegistrationWaiverView,
    StartApplicationRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import request_ip, require_persona

router = APIRouter(tags=["parent.onboarding"])
logger = logging.getLogger(__name__)


async def _waiver_flags(use_cases: ParentUseCases, app: Any) -> tuple[bool, bool]:
    """(class_first, waiver_to_sign) for the stepper.

    S47 / D-11: no required waiver to sign (none published, or only the starter
    placeholder) means the wizard skips the waiver step. A failed read keeps
    the step, so a hiccup never silently drops a real waiver.
    """
    get_waivers = getattr(use_cases, "get_registration_waivers", None)
    if not get_waivers:
        return False, True
    try:
        waivers, class_first = await get_waivers(None)
        if class_first and app.selected_session_id:
            waivers, _ = await get_waivers(app.selected_session_id)
    except Exception:
        return False, True
    # Class-first with no class chosen yet: the set is unknown, keep the step.
    unknown = class_first and not app.selected_session_id
    return bool(class_first), bool(waivers) or unknown


async def _app_view(use_cases: ParentUseCases, app: Any) -> ApplicationView:
    class_first, to_sign = await _waiver_flags(use_cases, app)
    return _view(app, class_first=class_first, waiver_to_sign=to_sign)


def _view(app: Any, *, class_first: bool = False, waiver_to_sign: bool = True) -> ApplicationView:
    return ApplicationView(
        application_id=app.application_id,
        status=app.status,
        parent_profile=ParentProfileView(**app.parent_profile.model_dump()),
        child_profile=ChildProfileView(**app.child_profile.model_dump()),
        selected_session_id=app.selected_session_id,
        waiver_accepted=app.waiver_acceptance is not None,
        waiver_class_first=class_first,
        waiver_to_sign=waiver_to_sign,
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
    body: StartApplicationRequest | None = Body(default=None),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ApplicationView:
    app = await use_cases.start_application.execute(
        StartApplicationCommand(
            parent_user_id=claims.user_id,
            parent_email=claims.email,
            application_id=body.application_id if body else None,
        )
    )
    return await _app_view(use_cases, app)


@router.patch(
    "/onboarding/{application_id}",
    response_model=ApplicationView,
    summary="Patch an in-progress onboarding application",
)
async def patch(
    application_id: str,
    body: PatchApplicationRequest,
    request: Request,
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
            signer_name=body.signer_name,
            consent=body.consent,
            initials=body.initials,
            ip_address=request_ip(request) if body.accept_waiver else None,
            user_agent=request.headers.get("user-agent") if body.accept_waiver else None,
        )
    )
    fill_blanks = getattr(use_cases, "fill_parent_profile_blanks", None)
    if body.parent_profile and fill_blanks:
        parent = body.parent_profile
        name = f"{parent.first_name.strip()} {parent.last_name.strip()}".strip()
        try:
            await fill_blanks(claims.user_id, name or None, parent.phone or None)
        except Exception:
            # The application already saved; a profile copy must not fail the step.
            logger.warning("onboarding: could not copy parent details to profile", exc_info=True)
    return await _app_view(use_cases, app)


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
    return await _app_view(use_cases, app)


@router.get(
    "/registrations",
    response_model=ParentRegistrationList,
    summary="The family's registrations that are not finished or not yet confirmed",
)
async def list_registrations(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentRegistrationList:
    list_rows: Any = use_cases.list_parent_registrations
    assert list_rows is not None  # wired by compose_parent
    rows = await list_rows(claims.user_id)
    return ParentRegistrationList(registrations=[ParentRegistrationView(**r) for r in rows])
