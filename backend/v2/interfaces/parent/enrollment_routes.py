"""Parent billing enrollment routes.

POST /parent/billing-enrollments        — self-enroll child in a session type
POST /parent/billing-enrollments/{id}/cancel — cancel a billing enrollment

Note: /parent/enrollments (session-roster) already exists in onboarding_routes /
session_routes; these routes use a distinct path to avoid collision.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.contexts.billing.application.use_cases.enroll_child_in_session_type import (
    EnrollChildCommand,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    BillingEnrollmentResponse,
    CancelBillingEnrollmentResponse,
    EnrollChildRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.billing_enrollments"])


@router.post(
    "/billing-enrollments",
    response_model=BillingEnrollmentResponse,
    status_code=201,
    summary="Parent self-enrolls a child in a session type",
)
async def enroll_child(
    body: EnrollChildRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> BillingEnrollmentResponse:
    result = await use_cases.enroll_child(  # type: ignore[operator]
        EnrollChildCommand(
            parent_id=claims.user_id,
            student_id=body.student_id,
            session_type_id=body.session_type_id,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
    )
    enrollment = result["enrollment"]
    return BillingEnrollmentResponse(
        enrollment_id=enrollment.enrollment_id,
        student_id=enrollment.student_id,
        parent_id=enrollment.parent_id,
        session_type_id=enrollment.session_type_id,
        status=enrollment.status,
        redirect_url=result["redirect_url"],
        stripe_subscription_id=enrollment.stripe_subscription_id,
        billing_start_date=enrollment.billing_start_date,
        enrolled_at=enrollment.enrolled_at,
    )


@router.post(
    "/billing-enrollments/{enrollment_id}/cancel",
    response_model=CancelBillingEnrollmentResponse,
    summary="Parent cancels a billing enrollment at period end",
)
async def cancel_billing_enrollment(
    enrollment_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> CancelBillingEnrollmentResponse:
    updated = await use_cases.cancel_billing_enrollment(  # type: ignore[operator]
        parent_id=claims.user_id,
        enrollment_id=enrollment_id,
    )
    return CancelBillingEnrollmentResponse(
        enrollment_id=updated.enrollment_id,
        status=updated.status,
    )
