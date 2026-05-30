"""Admin session-type billing routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from backend.v2.contexts.billing.application.use_cases.session_type_ops import (
    CreateSessionTypeCommand,
    MoveStudentSessionTypeCommand,
    OverrideStudentPriceCommand,
    UpdateSessionTypeCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    CreateSessionTypeRequest,
    MoveBillingEnrollmentRequest,
    MoveBillingEnrollmentResponse,
    OverrideStudentPriceRequest,
    SessionTypeList,
    SessionTypeProrationView,
    SessionTypeView,
    StudentBillingEnrollmentList,
    StudentBillingEnrollmentView,
    UpdateSessionTypeRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.session-types"])


def _session_type_view(session_type) -> SessionTypeView:
    return SessionTypeView(**session_type.model_dump(exclude={"academy_id"}))


def _billing_enrollment_view(enrollment) -> StudentBillingEnrollmentView:
    return StudentBillingEnrollmentView(**enrollment.model_dump(exclude={"academy_id"}))


@router.get("/session-types", response_model=SessionTypeList)
async def list_session_types(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SessionTypeList:
    rows = await use_cases.list_session_types.execute()  # type: ignore[union-attr]
    return SessionTypeList(session_types=[_session_type_view(row) for row in rows])


@router.post(
    "/session-types",
    response_model=SessionTypeView,
    status_code=status.HTTP_201_CREATED,
)
async def create_session_type(
    body: CreateSessionTypeRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SessionTypeView:
    row = await use_cases.create_session_type.execute(  # type: ignore[union-attr]
        CreateSessionTypeCommand(**body.model_dump())
    )
    return _session_type_view(row)


@router.patch("/session-types/{session_type_id}", response_model=SessionTypeView)
async def update_session_type(
    session_type_id: str,
    body: UpdateSessionTypeRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SessionTypeView:
    row = await use_cases.update_session_type.execute(  # type: ignore[union-attr]
        UpdateSessionTypeCommand(
            session_type_id=session_type_id,
            **body.model_dump(exclude_unset=True),
        )
    )
    return _session_type_view(row)


@router.delete(
    "/session-types/{session_type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_session_type(
    session_type_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.soft_delete_session_type.execute(session_type_id)  # type: ignore[union-attr]


@router.get("/billing-enrollments", response_model=StudentBillingEnrollmentList)
async def list_billing_enrollments(
    student_id: str | None = Query(default=None),
    parent_id: str | None = Query(default=None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> StudentBillingEnrollmentList:
    rows = await use_cases.list_student_billing_enrollments.execute(  # type: ignore[union-attr]
        student_id=student_id,
        parent_id=parent_id,
    )
    return StudentBillingEnrollmentList(enrollments=[_billing_enrollment_view(row) for row in rows])


@router.post(
    "/billing-enrollments/{enrollment_id}/move",
    response_model=MoveBillingEnrollmentResponse,
)
async def move_billing_enrollment(
    enrollment_id: str,
    body: MoveBillingEnrollmentRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> MoveBillingEnrollmentResponse:
    result = await use_cases.move_student_session_type.execute(  # type: ignore[union-attr]
        MoveStudentSessionTypeCommand(
            enrollment_id=enrollment_id,
            actor_id=claims.user_id,
            **body.model_dump(),
        )
    )
    return MoveBillingEnrollmentResponse(
        enrollment=_billing_enrollment_view(result.enrollment),
        proration=SessionTypeProrationView(**result.proration.model_dump()),
        stripe_invoice_id=result.stripe_invoice_id,
    )


@router.post(
    "/billing-enrollments/{enrollment_id}/override",
    response_model=StudentBillingEnrollmentView,
)
async def override_billing_enrollment_price(
    enrollment_id: str,
    body: OverrideStudentPriceRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> StudentBillingEnrollmentView:
    row = await use_cases.override_student_price.execute(  # type: ignore[union-attr]
        OverrideStudentPriceCommand(
            enrollment_id=enrollment_id,
            override_price_cents=body.override_price_cents,
        )
    )
    return _billing_enrollment_view(row)
