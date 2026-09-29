"""Admin BFF: ``/admin/pricing`` (Settings overhaul Phase 3 PR 11b).

The Pricing page under Money. Owner only, reads included: every route is in
``OWNER_ONLY_ROUTE_PATHS`` behind :func:`require_owner_or_403` (a plain admin
gets a 403 the page can show). The plan list itself is still edited through
``/admin/session-types`` (owner-only writes since PR 5).

Nothing here changes what anyone is charged: linking a class to a plan is a
label, and billing keeps reading the class's own monthly fee. The use cases
are attached at ``app.state.admin_pricing`` by ``composition/pricing.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.use_cases.pricing_page import (
    PricingClassRow,
    PricingOverview,
    SetClassPlanLinkCommand,
)
from backend.v2.interfaces.admin.owner_gate import require_owner_or_403
from backend.v2.shared.auth.claims import AuthClaims

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


class _Overview(Protocol):
    async def execute(self) -> PricingOverview: ...


class _SetLink(Protocol):
    async def execute(self, cmd: SetClassPlanLinkCommand) -> PricingClassRow: ...


class _LinkMatching(Protocol):
    async def execute(self, *, academy_id: str, actor_id: str) -> Any: ...


class AdminPricingLike(Protocol):
    overview: _Overview
    set_link: _SetLink
    link_matching: _LinkMatching


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
