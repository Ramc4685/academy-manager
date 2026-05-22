"""Platform-admin routes for SaaS platform billing."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.platform.billing.application.use_cases.manage_platform_billing import (
    ActivateTenantSubscriptionCommand,
    PlanLimitReport,
    PlatformBillingUseCases,
    PlatformUsage,
    ScheduleTenantCancellationCommand,
    StartTenantTrialCommand,
    UpsertPlatformPlanCommand,
)
from backend.v2.interfaces.platform.bootstrap_routes import require_platform_admin
from backend.v2.shared.auth.claims import AuthClaims

router = APIRouter(prefix="/platform/billing", tags=["platform-billing"])


class PlanLimitsPayload(BaseModel):
    max_active_students: int | None = Field(default=None, ge=0)
    max_locations: int | None = Field(default=None, ge=0)
    max_staff_members: int | None = Field(default=None, ge=0)


class UpsertPlanRequest(BaseModel):
    code: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    monthly_price_cents: int = Field(ge=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    limits: PlanLimitsPayload = Field(default_factory=PlanLimitsPayload)
    status: str = "active"
    stripe_price_id: str | None = None


class PlatformPlanResponse(BaseModel):
    plan_id: str
    code: str
    display_name: str
    monthly_price_cents: int
    currency: str
    limits: PlanLimitsPayload
    status: str
    stripe_price_id: str | None = None
    created_at: datetime
    updated_at: datetime


class TenantSubscriptionResponse(BaseModel):
    subscription_id: str
    academy_id: str
    plan_id: str
    billing_status: str
    trial_status: str
    cancellation_status: str
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    trial_started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    cancel_at_period_end: bool
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class StartTrialRequest(BaseModel):
    plan_id: str = Field(min_length=1)
    trial_ends_at: datetime


class ActivateSubscriptionRequest(BaseModel):
    plan_id: str = Field(min_length=1)
    stripe_customer_id: str = Field(min_length=1)
    stripe_subscription_id: str = Field(min_length=1)
    current_period_start: datetime
    current_period_end: datetime


class PlatformUsageRequest(BaseModel):
    active_students: int = Field(ge=0)
    locations: int = Field(ge=0)
    staff_members: int = Field(ge=0)


class PlanLimitReportResponse(BaseModel):
    academy_id: str
    plan_id: str
    limits: PlanLimitsPayload
    usage: PlatformUsageRequest
    allowed: bool
    violations: list[str]


def get_platform_billing(request: Request) -> PlatformBillingUseCases:
    use_cases = getattr(request.app.state, "platform_billing", None)
    if use_cases is None:
        raise HTTPException(status_code=503, detail="Platform billing is not configured")
    return use_cases  # type: ignore[no-any-return]


@router.get("/plans", response_model=list[PlatformPlanResponse])
async def list_plans(
    _: AuthClaims = Depends(require_platform_admin),
    billing: PlatformBillingUseCases = Depends(get_platform_billing),
) -> list[PlatformPlanResponse]:
    return [_plan_response(plan) for plan in await billing.list_plans.execute()]


@router.put("/plans/{plan_id}", response_model=PlatformPlanResponse)
async def upsert_plan(
    plan_id: str,
    payload: UpsertPlanRequest,
    _: AuthClaims = Depends(require_platform_admin),
    billing: PlatformBillingUseCases = Depends(get_platform_billing),
) -> PlatformPlanResponse:
    command = UpsertPlatformPlanCommand.model_validate(
        {
            **payload.model_dump(),
            "plan_id": plan_id,
            "limits": payload.limits.model_dump(),
        }
    )
    plan = await billing.upsert_plan.execute(command)
    return _plan_response(plan)


@router.get("/tenants/{academy_id}/subscription", response_model=TenantSubscriptionResponse)
async def get_tenant_subscription(
    academy_id: str,
    _: AuthClaims = Depends(require_platform_admin),
    billing: PlatformBillingUseCases = Depends(get_platform_billing),
) -> TenantSubscriptionResponse:
    return _subscription_response(await billing.get_subscription.execute(academy_id))


@router.post("/tenants/{academy_id}/trial", response_model=TenantSubscriptionResponse)
async def start_trial(
    academy_id: str,
    payload: StartTrialRequest,
    _: AuthClaims = Depends(require_platform_admin),
    billing: PlatformBillingUseCases = Depends(get_platform_billing),
) -> TenantSubscriptionResponse:
    subscription = await billing.start_trial.execute(
        StartTenantTrialCommand(
            academy_id=academy_id,
            plan_id=payload.plan_id,
            trial_ends_at=payload.trial_ends_at,
        )
    )
    return _subscription_response(subscription)


@router.post(
    "/tenants/{academy_id}/activate-subscription",
    response_model=TenantSubscriptionResponse,
)
async def activate_subscription(
    academy_id: str,
    payload: ActivateSubscriptionRequest,
    _: AuthClaims = Depends(require_platform_admin),
    billing: PlatformBillingUseCases = Depends(get_platform_billing),
) -> TenantSubscriptionResponse:
    subscription = await billing.activate_subscription.execute(
        ActivateTenantSubscriptionCommand(
            academy_id=academy_id,
            plan_id=payload.plan_id,
            stripe_customer_id=payload.stripe_customer_id,
            stripe_subscription_id=payload.stripe_subscription_id,
            current_period_start=payload.current_period_start,
            current_period_end=payload.current_period_end,
        )
    )
    return _subscription_response(subscription)


@router.post(
    "/tenants/{academy_id}/schedule-cancellation",
    response_model=TenantSubscriptionResponse,
)
async def schedule_cancellation(
    academy_id: str,
    _: AuthClaims = Depends(require_platform_admin),
    billing: PlatformBillingUseCases = Depends(get_platform_billing),
) -> TenantSubscriptionResponse:
    subscription = await billing.schedule_cancellation.execute(
        ScheduleTenantCancellationCommand(
            academy_id=academy_id,
            cancel_at_period_end=True,
        )
    )
    return _subscription_response(subscription)


@router.post("/tenants/{academy_id}/cancel-now", response_model=TenantSubscriptionResponse)
async def cancel_immediately(
    academy_id: str,
    _: AuthClaims = Depends(require_platform_admin),
    billing: PlatformBillingUseCases = Depends(get_platform_billing),
) -> TenantSubscriptionResponse:
    subscription = await billing.schedule_cancellation.execute(
        ScheduleTenantCancellationCommand(
            academy_id=academy_id,
            cancel_at_period_end=False,
        )
    )
    return _subscription_response(subscription)


@router.post("/tenants/{academy_id}/check-limits", response_model=PlanLimitReportResponse)
async def check_plan_limits(
    academy_id: str,
    payload: PlatformUsageRequest,
    _: AuthClaims = Depends(require_platform_admin),
    billing: PlatformBillingUseCases = Depends(get_platform_billing),
) -> PlanLimitReportResponse:
    report = await billing.check_limits.execute(
        academy_id=academy_id,
        usage=PlatformUsage(**payload.model_dump()),
    )
    return _limit_report_response(report)


def _plan_response(plan: Any) -> PlatformPlanResponse:
    return PlatformPlanResponse(
        **plan.model_dump(exclude={"limits"}),
        limits=PlanLimitsPayload(**plan.limits.model_dump()),
    )


def _subscription_response(subscription: Any) -> TenantSubscriptionResponse:
    return TenantSubscriptionResponse(**subscription.model_dump())


def _limit_report_response(report: PlanLimitReport) -> PlanLimitReportResponse:
    return PlanLimitReportResponse(
        academy_id=report.academy_id,
        plan_id=report.plan_id,
        limits=PlanLimitsPayload(**report.limits.model_dump()),
        usage=PlatformUsageRequest(**report.usage.model_dump()),
        allowed=report.allowed,
        violations=report.violations,
    )
