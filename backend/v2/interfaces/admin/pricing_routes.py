"""Admin BFF: ``/admin/pricing`` (Settings overhaul Phase 3 PR 11b).

The Pricing page under Money. Owner only, reads included: every route but
``GET /pricing/scheduled-class-fees`` (the class editor's "Scheduled" note,
open to every admin) is in ``OWNER_ONLY_ROUTE_PATHS`` behind
:func:`require_owner_or_403` (a plain admin gets a 403 the page can show).
The plan list itself is still edited through ``/admin/session-types``
(owner-only writes since PR 5).

Linking a class to a plan is a label, and billing keeps reading the class's
own monthly fee. The one thing here that changes a charge is a scheduled plan
price change (PR 26), and only for billing months on or after the month the
owner picked; invoices already generated never change. The use cases
are attached at ``app.state.admin_pricing`` by ``composition/pricing.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.use_cases.plan_price_changes import (
    PlanPriceChangePreview,
    PlanPriceChangeView,
    ScheduledClassFee,
    SchedulePlanPriceChangeCommand,
)
from backend.v2.contexts.billing.application.use_cases.pricing_page import (
    PricingClassRow,
    PricingOverview,
    SetClassPlanLinkCommand,
)
from backend.v2.interfaces.admin.owner_gate import require_owner_or_403
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.pricing"])


class PricingPlanView(BaseModel):
    plan_id: str
    name: str
    description: str | None = None
    price_cents: int
    plan_type: Literal["monthly", "per_session"]
    is_active: bool
    linked_classes: int
    updated_at: datetime
    #: A scheduled price change for this plan (PR 26).
    scheduled_change_id: str | None = None
    scheduled_cents: int | None = None
    scheduled_from: str | None = None


class PricingClassView(BaseModel):
    session_id: str
    title: str
    #: What the class is charged per month (its own fee; unchanged by links).
    charged_cents: int
    fee_set: bool
    students: int
    #: Linked plan, or null for "Custom".
    plan_id: str | None
    #: Active plans at exactly this fee: the only plans the class may use.
    matching_plan_ids: list[str]
    stale_link: bool
    stale_reason: Literal["archived", "price_changed", "plan_removed"] | None = None
    #: "Scheduled: $X from <Month>": a plan price change will move this fee.
    scheduled_cents: int | None = None
    scheduled_from: str | None = None


class PricingSavedOverrideView(BaseModel):
    source: Literal["billing_plan", "class_enrollment"]
    enrollment_id: str
    student_id: str | None
    student_name: str | None
    label: str | None
    override_cents: int
    charged_cents: int | None
    status: str | None


class PricingOverviewView(BaseModel):
    plans: list[PricingPlanView]
    classes: list[PricingClassView]
    saved_overrides: list[PricingSavedOverrideView]
    auto_linkable: int


class SetClassPlanRequest(BaseModel):
    #: A plan id at exactly the class fee, or null for "Custom".
    plan_id: str | None = Field(default=None, min_length=1, max_length=64)


class LinkMatchingClassesView(BaseModel):
    linked: int
    no_match: int
    several_matches: int
    already_decided: int


_PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class SchedulePriceChangeRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=64)
    new_price_cents: int = Field(ge=0, le=100_000_000)
    #: ``YYYY-MM``: the first month charged the new price.
    effective_period: str = Field(pattern=_PERIOD_PATTERN)


class _Overview(Protocol):
    async def execute(self) -> PricingOverview: ...


class _SetLink(Protocol):
    async def execute(self, cmd: SetClassPlanLinkCommand) -> PricingClassRow: ...


class _LinkMatching(Protocol):
    async def execute(self, *, academy_id: str, actor_id: str) -> Any: ...


class _Preview(Protocol):
    async def execute(
        self, *, plan_id: str, new_price_cents: int, effective_period: str | None = None
    ) -> PlanPriceChangePreview: ...


class _Schedule(Protocol):
    async def execute(self, cmd: SchedulePlanPriceChangeCommand) -> PlanPriceChangeView: ...


class _Cancel(Protocol):
    async def execute(self, *, academy_id: str, change_id: str, actor_id: str) -> None: ...


class _ScheduledFees(Protocol):
    async def execute(self) -> list[ScheduledClassFee]: ...


class AdminPricingLike(Protocol):
    overview: _Overview
    set_link: _SetLink
    link_matching: _LinkMatching
    preview_price_change: _Preview
    schedule_price_change: _Schedule
    cancel_price_change: _Cancel
    scheduled_class_fees: _ScheduledFees


def get_admin_pricing(request: Request) -> AdminPricingLike:
    pricing: AdminPricingLike = request.app.state.admin_pricing
    return pricing


def _class_view(row: PricingClassRow) -> PricingClassView:
    return PricingClassView(**row.model_dump())


@router.get(
    "/pricing",
    response_model=PricingOverviewView,
    summary="Plans, where each class's price comes from, saved overrides (owner only)",
)
async def get_pricing(
    _claims: AuthClaims = Depends(require_owner_or_403()),
    pricing: AdminPricingLike = Depends(get_admin_pricing),
) -> PricingOverviewView:
    overview = await pricing.overview.execute()
    return PricingOverviewView(
        plans=[
            PricingPlanView(
                plan_id=row.plan.session_type_id,
                name=row.plan.name,
                description=row.plan.description,
                price_cents=row.plan.price_cents,
                plan_type=row.plan.plan_type,
                is_active=row.plan.is_active,
                linked_classes=row.linked_classes,
                updated_at=row.plan.updated_at,
                scheduled_change_id=row.scheduled_change_id,
                scheduled_cents=row.scheduled_cents,
                scheduled_from=row.scheduled_from,
            )
            for row in overview.plans
        ],
        classes=[_class_view(row) for row in overview.classes],
        saved_overrides=[
            PricingSavedOverrideView(**row.model_dump()) for row in overview.saved_overrides
        ],
        auto_linkable=overview.auto_linkable,
    )


@router.put(
    "/pricing/classes/{session_id}/plan",
    response_model=PricingClassView,
    summary="Link a class to a plan at its own fee, or mark it custom (owner only)",
)
async def set_class_plan(
    session_id: str,
    body: SetClassPlanRequest,
    claims: AuthClaims = Depends(require_owner_or_403()),
    pricing: AdminPricingLike = Depends(get_admin_pricing),
) -> PricingClassView:
    row = await pricing.set_link.execute(
        SetClassPlanLinkCommand(
            academy_id=claims.academy_id,
            session_id=session_id,
            plan_id=body.plan_id,
            actor_id=claims.user_id,
        )
    )
    return _class_view(row)


@router.post(
    "/pricing/link-matching-classes",
    response_model=LinkMatchingClassesView,
    summary="Link each undecided class to the one plan at its fee (owner only)",
)
async def link_matching_classes(
    claims: AuthClaims = Depends(require_owner_or_403()),
    pricing: AdminPricingLike = Depends(get_admin_pricing),
) -> LinkMatchingClassesView:
    result = await pricing.link_matching.execute(
        academy_id=claims.academy_id, actor_id=claims.user_id
    )
    return LinkMatchingClassesView(**result.model_dump())


# ------------------------------------------------ change a plan price (PR 26)


@router.get(
    "/pricing/price-changes/preview",
    response_model=PlanPriceChangePreview,
    summary="Preview a plan price change from a future month (owner only, read only)",
)
async def preview_price_change(
    plan_id: str = Query(min_length=1, max_length=64),
    new_price_cents: int = Query(ge=0, le=100_000_000),
    effective_period: str | None = Query(default=None, pattern=_PERIOD_PATTERN),
    _claims: AuthClaims = Depends(require_owner_or_403()),
    pricing: AdminPricingLike = Depends(get_admin_pricing),
) -> PlanPriceChangePreview:
    return await pricing.preview_price_change.execute(
        plan_id=plan_id, new_price_cents=new_price_cents, effective_period=effective_period
    )


@router.post(
    "/pricing/price-changes",
    response_model=PlanPriceChangeView,
    status_code=201,
    summary="Schedule a plan price change from a future month (owner only, audited)",
)
async def schedule_price_change(
    body: SchedulePriceChangeRequest,
    claims: AuthClaims = Depends(require_owner_or_403()),
    pricing: AdminPricingLike = Depends(get_admin_pricing),
) -> PlanPriceChangeView:
    return await pricing.schedule_price_change.execute(
        SchedulePlanPriceChangeCommand(
            academy_id=claims.academy_id,
            plan_id=body.plan_id,
            new_price_cents=body.new_price_cents,
            effective_period=body.effective_period,
            actor_id=claims.user_id,
        )
    )


@router.delete(
    "/pricing/price-changes/{change_id}",
    status_code=204,
    summary="Cancel a scheduled plan price change before its month (owner only, audited)",
)
async def cancel_price_change(
    change_id: str,
    claims: AuthClaims = Depends(require_owner_or_403()),
    pricing: AdminPricingLike = Depends(get_admin_pricing),
) -> Response:
    await pricing.cancel_price_change.execute(
        academy_id=claims.academy_id, change_id=change_id, actor_id=claims.user_id
    )
    return Response(status_code=204)


@router.get(
    "/pricing/scheduled-class-fees",
    response_model=list[ScheduledClassFee],
    summary="Classes whose monthly fee a scheduled plan price change will move",
)
async def scheduled_class_fees(
    _claims: AuthClaims = Depends(require_persona("admin")),
    pricing: AdminPricingLike = Depends(get_admin_pricing),
) -> list[ScheduledClassFee]:
    """Admin-readable: the class editor shows "Scheduled: $X from <Month>".

    The one Pricing route open to every admin. Admins already see each class
    fee in the class editor; this only adds the scheduled one next to it.
    """
    return await pricing.scheduled_class_fees.execute()
