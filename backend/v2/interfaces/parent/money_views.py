"""``GET /parent/money-summary`` (S57; spec docs/design/parent-money.md §7.1).

One figure, one date and per-child lines, all computed by the backend from the
caller's own issued invoices. The family is always ``claims.user_id``.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.invoices"])


class ParentMoneyLineView(BaseModel):
    kind: Literal["child", "discount", "paid"]
    student_id: str | None = None
    label: str
    detail: str | None = None
    amount_cents: int


class ParentMoneyPeriodView(BaseModel):
    period: str
    label: str
    billed_cents: int
    paid_cents: int
    due_cents: int


class ParentLastPaymentView(BaseModel):
    amount_cents: int
    paid_on: date | None = None
    method_label: str


class ParentMoneySummaryView(BaseModel):
    currency: str
    amount_due_cents: int
    due_date: date | None = None
    overdue: bool
    days_overdue: int
    multiple_due_dates: bool
    can_pay_online: bool
    lines: list[ParentMoneyLineView]
    periods: list[ParentMoneyPeriodView]
    last_payment: ParentLastPaymentView | None = None


@router.get(
    "/money-summary",
    response_model=ParentMoneySummaryView,
    summary="What the family owes now, by child, with one due date",
)
async def get_money_summary(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentMoneySummaryView:
    money = getattr(use_cases, "parent_money", None)
    if money is None:
        raise HTTPException(status_code=503, detail="Money summary is not configured")
    return ParentMoneySummaryView.model_validate(await money.summary(claims.user_id))
