"""Admin BFF: ``/admin/billing/family-offers`` — Settings -> Billing rules -> Family offers.

L9 C1. The read is admin persona; the write is **owner only** (listed in
``OWNER_ONLY_ROUTE_PATHS``) because the sibling discount changes what
families are charged. The use cases are attached at
``app.state.admin_family_offers`` by ``composition/family_offers.py``.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from backend.v2.contexts.billing.application.use_cases.billing_rules import (
    BillingRulesValidationError,
)
from backend.v2.contexts.billing.application.use_cases.family_offers import (
    UpdateFamilyOffersCommand,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner, require_persona

_Trigger = Literal["first_paid_invoice", "first_paid_monthly_invoice"]
_FullPriceChild = Literal["highest_tuition", "lowest_tuition", "first_enrolled"]
_AppliesTo = Literal["all_classes", "one_class_per_child"]


class ReferralProgramView(BaseModel):
    enabled: bool
    referrer_credit_cents: int | None = None
    referred_credit_cents: int | None = None
    hold_days: int | None = None
    max_rewards_per_referrer_per_year: int | None = None
    credit_expiry_days: int | None = None
    trigger: _Trigger | None = None
    effective_from: str | None = None


class SiblingDiscountView(BaseModel):
    enabled: bool
    percent_bps: int | None = None
    full_price_child: _FullPriceChild | None = None
    applies_to: _AppliesTo | None = None


class FamilyOffersResponse(BaseModel):
    referral_program: ReferralProgramView
    sibling_discount: SiblingDiscountView


class ReferralProgramRequest(BaseModel):
    """Partial: only the keys sent change. No bounds here on purpose; the use
    case owns them so one path names the offending field in the 422.
    ``effective_from`` is server-stamped and refused."""

    model_config = {"extra": "forbid"}

    enabled: bool | None = None
    referrer_credit_cents: int | None = None
    referred_credit_cents: int | None = None
    hold_days: int | None = None
    max_rewards_per_referrer_per_year: int | None = None
    credit_expiry_days: int | None = None
    trigger: _Trigger | None = None


class SiblingDiscountRequest(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool | None = None
    percent_bps: int | None = None
    full_price_child: _FullPriceChild | None = None
    applies_to: _AppliesTo | None = None


class UpdateFamilyOffersRequest(BaseModel):
    model_config = {"extra": "forbid"}

    referral_program: ReferralProgramRequest | None = None
    sibling_discount: SiblingDiscountRequest | None = None
    reason: str | None = None


class _Reader(Protocol):
    async def execute(self) -> Any: ...


class _Writer(Protocol):
    async def execute(self, academy_id: str, cmd: UpdateFamilyOffersCommand) -> Any: ...


class AdminFamilyOffersLike(Protocol):
    read: _Reader
    write: _Writer


def get_admin_family_offers(request: Request) -> AdminFamilyOffersLike:
    offers: AdminFamilyOffersLike = request.app.state.admin_family_offers
    return offers


def _response(view: Any) -> FamilyOffersResponse:
    return FamilyOffersResponse.model_validate(view.model_dump(mode="json"))


router = APIRouter(tags=["admin.family-offers"])


@router.get(
    "/billing/family-offers",
    response_model=FamilyOffersResponse,
    summary="The referral programme and sibling discount settings",
)
async def get_family_offers(
    claims: AuthClaims = Depends(require_persona("admin")),
    offers: AdminFamilyOffersLike = Depends(get_admin_family_offers),
) -> FamilyOffersResponse:
    return _response(await offers.read.execute())


@router.put(
    "/billing/family-offers",
    response_model=FamilyOffersResponse,
    summary="Set the family offers (owner only, audited)",
)
async def set_family_offers(
    body: UpdateFamilyOffersRequest,
    claims: AuthClaims = Depends(require_owner()),
    offers: AdminFamilyOffersLike = Depends(get_admin_family_offers),
) -> FamilyOffersResponse:
    try:
        view = await offers.write.execute(
            claims.academy_id,
            UpdateFamilyOffersCommand(
                referral_program=(
                    body.referral_program.model_dump(exclude_unset=True)
                    if body.referral_program is not None
                    else None
                ),
                sibling_discount=(
                    body.sibling_discount.model_dump(exclude_unset=True)
                    if body.sibling_discount is not None
                    else None
                ),
                actor_id=claims.user_id,
                reason=body.reason,
            ),
        )
    except BillingRulesValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"field": exc.field, "message": exc.message},
        ) from exc
    return _response(view)
