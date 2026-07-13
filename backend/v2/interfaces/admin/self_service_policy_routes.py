"""Admin routes for the per-academy parent self-service policy."""

from __future__ import annotations

from typing import Literal, Protocol

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.use_cases.self_service_policies import (
    UpdateSelfServicePolicyCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.self-service"])


class _PolicyLike(Protocol):
    """Shape of ParentSelfServicePolicy, referenced structurally.

    Interface modules never import domain types directly (ADR-0006 import
    boundaries) — the use case returns the domain model, and this route only
    relies on its attributes.
    """

    absence_notice_min_hours: int
    makeup_expiry_days: int
    makeup_requires_notice: bool
    cancellation_minimum_notice_days: int
    cancellation_fee_cents: int
    cancellation_effective_timing: Literal["immediate", "end_of_period"]


class SelfServicePolicyView(BaseModel):
    absence_notice_min_hours: int
    makeup_expiry_days: int
    makeup_requires_notice: bool
    cancellation_minimum_notice_days: int
    cancellation_fee_cents: int
    cancellation_effective_timing: Literal["immediate", "end_of_period"]

    @staticmethod
    def from_domain(policy: _PolicyLike) -> SelfServicePolicyView:
        return SelfServicePolicyView(
            absence_notice_min_hours=policy.absence_notice_min_hours,
            makeup_expiry_days=policy.makeup_expiry_days,
            makeup_requires_notice=policy.makeup_requires_notice,
            cancellation_minimum_notice_days=policy.cancellation_minimum_notice_days,
            cancellation_fee_cents=policy.cancellation_fee_cents,
            cancellation_effective_timing=policy.cancellation_effective_timing,
        )


class UpdateSelfServicePolicyRequest(BaseModel):
    absence_notice_min_hours: int = Field(ge=0)
    makeup_expiry_days: int = Field(ge=0)
    makeup_requires_notice: bool
    cancellation_minimum_notice_days: int = Field(ge=0)
    cancellation_fee_cents: int = Field(ge=0)
    cancellation_effective_timing: Literal["immediate", "end_of_period"]


@router.get("/self-service/policy", response_model=SelfServicePolicyView)
async def get_self_service_policy(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SelfServicePolicyView:
    policy = await use_cases.self_service_policy.execute()
    return SelfServicePolicyView.from_domain(policy)


@router.put("/self-service/policy", response_model=SelfServicePolicyView)
async def update_self_service_policy(
    body: UpdateSelfServicePolicyRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SelfServicePolicyView:
    policy = await use_cases.update_self_service_policy.execute(
        UpdateSelfServicePolicyCommand(**body.model_dump())
    )
    return SelfServicePolicyView.from_domain(policy)
