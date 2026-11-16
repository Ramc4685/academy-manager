"""GET /api/v2/parent/referral: the parent's referral code and rewards (L9 C2).

While the academy's referral programme is off this returns ``enabled: false``
and reads or mints nothing. When on, the parent's stable code is minted on
first view; the frontend builds the share link from the academy's own host.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.referral"])


class ParentReferralResponse(BaseModel):
    enabled: bool
    referral_code: str | None = None
    #: The academy's own public page with ``?ref=<code>``, built server side.
    share_url: str | None = None
    rewards_earned: int = 0
    referrer_credit_cents: int | None = None
    referred_credit_cents: int | None = None


@router.get(
    "/referral",
    response_model=ParentReferralResponse,
    summary="The current parent's referral code and rewards earned",
)
async def get_referral(
    request: Request,
    claims: AuthClaims = Depends(require_persona("parent")),
) -> ParentReferralResponse:
    view = await request.app.state.referrals.parent_view.execute(claims.user_id)
    return ParentReferralResponse(
        enabled=view.enabled,
        referral_code=view.referral_code,
        share_url=view.share_url,
        rewards_earned=view.rewards_earned,
        referrer_credit_cents=view.referrer_credit_cents,
        referred_credit_cents=view.referred_credit_cents,
    )
