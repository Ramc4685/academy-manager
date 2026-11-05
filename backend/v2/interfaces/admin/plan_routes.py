"""Admin BFF: the academy's CourtMastr plan (AI strategy Phase 2, slice A2).

Owner only: ``GET /billing/plan`` is what the academy pays CourtMastr, and
``POST /billing/plan/checkout`` starts a Stripe Billing Checkout for the
Growth plan on the platform account. Services are attached at
``app.state.admin_plan`` by ``composition/platform_plan_checkout.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.v2.contexts.platform.billing.application.use_cases.plan_checkout import (
    StartGrowthCheckoutCommand,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner

router = APIRouter(prefix="/billing/plan", tags=["admin-plan"])


class AdminPlanServices(Protocol):
    get_overview: Any
    start_checkout: Any
    academy_frontend_base_url: Any
    academy_name: Any


def get_admin_plan(request: Request) -> AdminPlanServices:
    services: AdminPlanServices = request.app.state.admin_plan
    return services


class PlanSummary(BaseModel):
    code: str
    display_name: str
    monthly_price_cents: int
    features: list[str]


class SubscriptionSummary(BaseModel):
    billing_status: str
    cancel_at_period_end: bool
    current_period_end: datetime | None = None


class AdminPlanOverview(BaseModel):
    plan: PlanSummary | None = None
    subscription: SubscriptionSummary | None = None
    growth: PlanSummary | None = None
    checkout_available: bool


class PlanCheckoutView(BaseModel):
    url: str


def _plan_summary(plan: Any) -> PlanSummary | None:
    if plan is None:
        return None
    return PlanSummary(
        code=plan.code,
        display_name=plan.display_name,
        monthly_price_cents=plan.monthly_price_cents,
        features=sorted(plan.features),
    )


@router.get("", response_model=AdminPlanOverview)
async def get_plan(
    claims: AuthClaims = Depends(require_owner()),
    services: AdminPlanServices = Depends(get_admin_plan),
) -> AdminPlanOverview:
    overview = await services.get_overview.execute(claims.academy_id)
    sub = overview.subscription
    return AdminPlanOverview(
        plan=_plan_summary(overview.plan),
        subscription=SubscriptionSummary(
            billing_status=sub.billing_status,
            cancel_at_period_end=sub.cancel_at_period_end,
            current_period_end=sub.current_period_end,
        )
        if sub
        else None,
        growth=_plan_summary(overview.growth),
        checkout_available=overview.checkout_available,
    )


@router.post("/checkout", response_model=PlanCheckoutView)
async def start_growth_checkout(
    request: Request,
    claims: AuthClaims = Depends(require_owner()),
    services: AdminPlanServices = Depends(get_admin_plan),
) -> PlanCheckoutView:
    frontend = str(await services.academy_frontend_base_url(claims.academy_id)).rstrip("/")
    settings_url = f"{frontend}/admin/settings?panel=integrations"
    url = await services.start_checkout.execute(
        StartGrowthCheckoutCommand(
            academy_id=claims.academy_id,
            academy_name=await services.academy_name(claims.academy_id),
            actor_user_id=claims.user_id,
            actor_email=claims.email,
            success_url=f"{settings_url}&plan=upgraded",
            cancel_url=f"{settings_url}&plan=cancelled",
            request_id=request.headers.get("x-request-id"),
            ip_address=request.client.host if request.client else None,
        )
    )
    return PlanCheckoutView(url=url)
