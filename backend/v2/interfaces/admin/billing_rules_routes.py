"""Admin BFF: ``/admin/billing/rules`` — the Settings -> Billing rules panel.

Spec: ``docs/superpowers/specs/2026-09-07-billing-rules-design.md`` SS4.

One read and one write for numbers that live in three different stores. The
read is admin persona; the write is **owner only** (listed in
``OWNER_ONLY_ROUTE_PATHS``) because it moves money timing and the late-fee
values. The use cases are attached at ``app.state.admin_billing_rules`` by
``composition/billing_rules.py`` — ``composition/admin.py`` is at its line
budget — so this module only knows their protocol.

The existing ``/academy/fees`` and ``/billing/settings/invoice-schedule``
routes are untouched and keep serving their other callers.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from backend.v2.contexts.billing.application.use_cases.billing_rules import (
    BillingRulesPartialWriteError,
    BillingRulesValidationError,
    UpdateBillingRulesCommand,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner, require_persona


class BillingRuleRowView(BaseModel):
    key: str
    label: str
    editable: bool
    value: int | None = None
    unit: str | None = None
    min_value: int | None = None
    max_value: int | None = None
    display: str | None = None
    detail: str | None = None


class BillingRuleGroupView(BaseModel):
    key: str
    title: str
    note: str | None = None
    rows: list[BillingRuleRowView]


class BillingRulesResponse(BaseModel):
    groups: list[BillingRuleGroupView]


class UpdateBillingRulesRequest(BaseModel):
    """Only the editable fields, all optional.

    No ``Field`` bounds here on purpose: the use case owns the bounds so one
    code path produces the 422 and names the offending field, whether the
    caller is HTTP or a future job.
    """

    billing_day: int | None = None
    invoice_due_days: int | None = None
    grace_days: int | None = None
    late_fee_cents: int | None = None
    cancellation_minimum_notice_days: int | None = None
    cancellation_fee_cents: int | None = None
    reason: str | None = None


class AdminBillingRulesReader(Protocol):
    async def execute(self, academy_id: str) -> Any: ...


class AdminBillingRulesWriter(Protocol):
    async def execute(self, academy_id: str, cmd: UpdateBillingRulesCommand) -> Any: ...


class AdminBillingRulesLike(Protocol):
    read: AdminBillingRulesReader
    write: AdminBillingRulesWriter


def get_admin_billing_rules(request: Request) -> AdminBillingRulesLike:
    rules: AdminBillingRulesLike = request.app.state.admin_billing_rules
    return rules


router = APIRouter(tags=["admin.billing-rules"])


@router.get(
    "/billing/rules",
    response_model=BillingRulesResponse,
    summary="Every billing rule, editable and fixed",
)
async def get_billing_rules(
    claims: AuthClaims = Depends(require_persona("admin")),
    rules: AdminBillingRulesLike = Depends(get_admin_billing_rules),
) -> BillingRulesResponse:
    view = await rules.read.execute(claims.academy_id)
    return BillingRulesResponse.model_validate(view.model_dump())


@router.put(
    "/billing/rules",
    response_model=BillingRulesResponse,
    summary="Set the editable billing rules (owner only, audited)",
)
async def set_billing_rules(
    body: UpdateBillingRulesRequest,
    claims: AuthClaims = Depends(require_owner()),
    rules: AdminBillingRulesLike = Depends(get_admin_billing_rules),
) -> BillingRulesResponse:
    try:
        await rules.write.execute(
            claims.academy_id,
            UpdateBillingRulesCommand(
                **body.model_dump(exclude={"reason"}),
                actor_id=claims.user_id,
                reason=body.reason,
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
                "message": "Some billing rules could not be saved.",
                "saved_fields": list(exc.applied_fields),
            },
        ) from exc
    view = await rules.read.execute(claims.academy_id)
    return BillingRulesResponse.model_validate(view.model_dump())
