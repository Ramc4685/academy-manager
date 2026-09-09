"""Admin routes for the per-academy EnrollmentDeparturePolicy (issue #697).

Structurally a copy of ``self_service_policy_routes.py``. The PUT is
owner-only (see ``domain/departure_policy.py`` §1.1 for why) — it is also
listed in ``owner_gate.OWNER_ONLY_ROUTE_PATHS`` in the same commit; the
structural test ``tests/structural/test_owner_gate_policy.py`` fails if
either half is missing.
"""

from __future__ import annotations

from typing import Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.use_cases.departure_policies import (
    GetEnrollmentDeparturePolicy,
    UpdateEnrollmentDeparturePolicy,
    UpdateEnrollmentDeparturePolicyCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner, require_persona

router = APIRouter(tags=["admin.enrollment-departure-policy"])


def _get_policy(use_cases: AdminUseCases) -> GetEnrollmentDeparturePolicy:
    use_case = use_cases.departure_policy
    if use_case is None:
        raise HTTPException(status_code=503, detail="Departure policy is not configured")
    return use_case


def _update_policy(use_cases: AdminUseCases) -> UpdateEnrollmentDeparturePolicy:
    use_case = use_cases.update_departure_policy
    if use_case is None:
        raise HTTPException(status_code=503, detail="Departure policy is not configured")
    return use_case


class _PolicyLike(Protocol):
    """Shape of EnrollmentDeparturePolicy, referenced structurally (ADR-0006:
    interface modules never import domain types directly)."""

    max_hold_days: int
    hold_reclaim_policy: Literal["longest_held", "never"]
    drop_default_outcome: Literal[
        "no_credit_mid_month", "credit_mid_month", "no_credit_end_of_period"
    ]
    delete_enrollment_requires_owner: bool


class EnrollmentDeparturePolicyView(BaseModel):
    max_hold_days: int
    hold_reclaim_policy: Literal["longest_held", "never"]
    drop_default_outcome: Literal[
        "no_credit_mid_month", "credit_mid_month", "no_credit_end_of_period"
    ]
    delete_enrollment_requires_owner: bool

    @staticmethod
    def from_domain(policy: _PolicyLike) -> EnrollmentDeparturePolicyView:
        return EnrollmentDeparturePolicyView(
            max_hold_days=policy.max_hold_days,
            hold_reclaim_policy=policy.hold_reclaim_policy,
            drop_default_outcome=policy.drop_default_outcome,
            delete_enrollment_requires_owner=policy.delete_enrollment_requires_owner,
        )


class UpdateEnrollmentDeparturePolicyRequest(BaseModel):
    max_hold_days: int = Field(ge=1, le=365)
    hold_reclaim_policy: Literal["longest_held", "never"]
    drop_default_outcome: Literal[
        "no_credit_mid_month", "credit_mid_month", "no_credit_end_of_period"
    ]
    delete_enrollment_requires_owner: bool


@router.get("/enrollment/departure-policy", response_model=EnrollmentDeparturePolicyView)
async def get_departure_policy(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> EnrollmentDeparturePolicyView:
    policy = await _get_policy(use_cases).execute()
    return EnrollmentDeparturePolicyView.from_domain(policy)


@router.put("/enrollment/departure-policy", response_model=EnrollmentDeparturePolicyView)
async def update_departure_policy(
    body: UpdateEnrollmentDeparturePolicyRequest,
    _claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> EnrollmentDeparturePolicyView:
    policy = await _update_policy(use_cases).execute(
        UpdateEnrollmentDeparturePolicyCommand(**body.model_dump())
    )
    return EnrollmentDeparturePolicyView.from_domain(policy)
