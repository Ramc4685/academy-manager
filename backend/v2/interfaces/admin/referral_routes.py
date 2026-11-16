"""Admin BFF: ``/admin/billing/referrals``: the referral list and email preview (L9 C2).

The list (admin persona) shows each referral's state: needs review (the code
came only from the public inquiry form), pending (the hold, or waiting for
the new family's first paid invoice), granted, or ineligible with its reason.
Approving a needs-review referral is **owner only** (it leads to a credit) and
records the approver on the row. The preview renders the two referral emails with
sample values; nothing sends them (owner sign-off pending).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from backend.v2.contexts.billing.application.use_cases.referrals import ReferralNotReviewable
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner, require_persona

router = APIRouter(tags=["admin.referrals"])


class ReferralRowView(BaseModel):
    referral_id: str
    referral_code: str
    referrer_name: str | None = None
    referred_name: str | None = None
    status: Literal["needs_review", "pending", "granted", "ineligible"]
    reason: (
        Literal["unknown_code", "self_referral", "existing_family", "yearly_cap_reached"] | None
    ) = None
    referrer_credit_cents: int | None = None
    referred_credit_cents: int | None = None
    qualified_at: datetime | None = None
    grant_due_at: datetime | None = None
    granted_at: datetime | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class ReferralListResponse(BaseModel):
    referrals: list[ReferralRowView]


class ReferralEmailView(BaseModel):
    key: str
    subject: str
    html: str


class ReferralEmailPreviewResponse(BaseModel):
    emails: list[ReferralEmailView]


@router.get(
    "/billing/referrals",
    response_model=ReferralListResponse,
    summary="The academy's referrals and their state",
)
async def list_referrals(
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
) -> ReferralListResponse:
    rows = await request.app.state.referrals.admin_list.execute()
    return ReferralListResponse(
        referrals=[
            ReferralRowView(
                **row.referral.model_dump(include=set(ReferralRowView.model_fields)),
                referrer_name=row.referrer_name,
                referred_name=row.referred_name,
            )
            for row in rows
        ]
    )


@router.get(
    "/billing/referrals/email-preview",
    response_model=ReferralEmailPreviewResponse,
    summary="Preview the referral emails (never sent)",
)
async def preview_referral_emails(
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
) -> ReferralEmailPreviewResponse:
    emails = await request.app.state.referrals.email_preview()
    return ReferralEmailPreviewResponse(
        emails=[ReferralEmailView(key=e.key, subject=e.subject, html=e.inner_html) for e in emails]
    )


@router.post(
    "/billing/referrals/{referral_id}/approve",
    response_model=ReferralRowView,
    summary="Approve a referral that came only from the website inquiry (owner only)",
)
async def approve_referral(
    referral_id: str,
    request: Request,
    claims: AuthClaims = Depends(require_owner()),
) -> ReferralRowView:
    try:
        referral = await request.app.state.referrals.approve.execute(
            referral_id, actor_id=claims.user_id
        )
    except ReferralNotReviewable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ReferralRowView(**referral.model_dump(include=set(ReferralRowView.model_fields)))
