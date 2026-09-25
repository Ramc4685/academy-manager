"""Admin routes for the per-academy parent self-service policy."""

from __future__ import annotations

from typing import Final, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.use_cases.billing_rules import (
    BillingRulesPartialWriteError,
    BillingRulesValidationError,
    UpdateBillingRulesCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.self_service_policies import (
    UpdateSelfServicePolicyCommand,
)
from backend.v2.interfaces.admin.billing_rules_routes import get_admin_billing_rules
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.owner_gate import ensure_owner_for_cancellation_terms
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
    """Any subset of the six fields; only the ones sent are written.

    The Settings page sends just the fields the admin changed. An older
    client that still sends all six is fine: a field equal to the stored value
    is not a change.
    """

    absence_notice_min_hours: int | None = Field(default=None, ge=0)
    makeup_expiry_days: int | None = Field(default=None, ge=1)
    makeup_requires_notice: bool | None = None
    cancellation_minimum_notice_days: int | None = Field(default=None, ge=0)
    cancellation_fee_cents: int | None = Field(default=None, ge=0)
    cancellation_effective_timing: Literal["immediate", "end_of_period"] | None = None


#: The two fields Billing rules also edits. A change to either goes through
#: ``UpdateBillingRules``: owner only, bounded, and audited.
CANCELLATION_TERMS: Final[tuple[str, ...]] = (
    "cancellation_minimum_notice_days",
    "cancellation_fee_cents",
)


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
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SelfServicePolicyView:
    reader = use_cases.self_service_policy
    writer = use_cases.update_self_service_policy
    if reader is None or writer is None:
        raise RuntimeError("self-service policy use cases are not wired on AdminUseCases")
    requested = body.model_dump(exclude_none=True)
    current = await reader.execute()
    cancellation = {
        key: requested[key]
        for key in CANCELLATION_TERMS
        if key in requested and requested[key] != getattr(current, key)
    }
    others = {key: value for key, value in requested.items() if key not in CANCELLATION_TERMS}

    if cancellation:
        # Money audit X5: this route used to write the cancellation fee with
        # no owner check, no bound and no audit, while Billing rules gated the
        # same values. It now takes the Billing rules path, which checks
        # bounds before any store is touched and writes the audit entry.
        ensure_owner_for_cancellation_terms(claims)
        try:
            await get_admin_billing_rules(request).write.execute(
                claims.academy_id,
                UpdateBillingRulesCommand(
                    **cancellation,
                    actor_id=claims.user_id,
                    reason="Settings -> Self-service",
                ),
            )
        except BillingRulesValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"field": exc.field, "message": exc.message},
            ) from exc
        except BillingRulesPartialWriteError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "message": "The cancellation terms could not be saved.",
                    "saved_fields": list(exc.applied_fields),
                },
            ) from exc

    if others:
        await writer.execute(UpdateSelfServicePolicyCommand(**others))
    return SelfServicePolicyView.from_domain(await reader.execute())
