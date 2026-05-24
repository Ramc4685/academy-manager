"""Admin registration review routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.composition.admin_registration_review import (
    AdminRegistrationReview,
    ApproveRegistrationCommand,
    RejectRegistrationCommand,
    WaitlistRegistrationCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminRegistrationApproveRequest,
    AdminRegistrationDetailView,
    AdminRegistrationListView,
    AdminRegistrationRejectRequest,
    AdminRegistrationRowView,
    AdminRegistrationWaitlistRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.registrations"])


def _review_use_case(use_cases: AdminUseCases) -> AdminRegistrationReview:
    use_case = use_cases.admin_registration_review
    if use_case is None:
        raise HTTPException(status_code=503, detail="Admin registration review is not configured")
    return use_case


@router.get("/registrations", response_model=AdminRegistrationListView)
async def list_admin_registrations(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminRegistrationListView:
    rows = await _review_use_case(use_cases).list_pending()
    return AdminRegistrationListView(
        registrations=[AdminRegistrationRowView(**r.model_dump()) for r in rows]
    )


@router.get("/registrations/{application_id}", response_model=AdminRegistrationDetailView)
async def get_admin_registration(
    application_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminRegistrationDetailView:
    detail = await _review_use_case(use_cases).detail(application_id)
    return AdminRegistrationDetailView(**detail.model_dump())


@router.post("/registrations/{application_id}/approve", response_model=AdminRegistrationDetailView)
async def approve_admin_registration(
    application_id: str,
    body: AdminRegistrationApproveRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminRegistrationDetailView:
    detail = await _review_use_case(use_cases).approve(
        ApproveRegistrationCommand(
            application_id=application_id,
            actor_id=claims.user_id,
            session_id=body.session_id,
            waiver_override_reason=body.waiver_override_reason,
        )
    )
    return AdminRegistrationDetailView(**detail.model_dump())


@router.post("/registrations/{application_id}/waitlist", response_model=AdminRegistrationDetailView)
async def waitlist_admin_registration(
    application_id: str,
    body: AdminRegistrationWaitlistRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminRegistrationDetailView:
    detail = await _review_use_case(use_cases).waitlist(
        WaitlistRegistrationCommand(
            application_id=application_id,
            actor_id=claims.user_id,
            session_id=body.session_id,
            reason=body.reason,
        )
    )
    return AdminRegistrationDetailView(**detail.model_dump())


@router.post("/registrations/{application_id}/reject", response_model=AdminRegistrationDetailView)
async def reject_admin_registration(
    application_id: str,
    body: AdminRegistrationRejectRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminRegistrationDetailView:
    detail = await _review_use_case(use_cases).reject(
        RejectRegistrationCommand(
            application_id=application_id,
            actor_id=claims.user_id,
            reason=body.reason,
        )
    )
    return AdminRegistrationDetailView(**detail.model_dump())
