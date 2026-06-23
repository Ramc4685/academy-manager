"""Set / remove recurring tuition discount policies (billing application layer)."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.domain.tuition_discount import (
    DiscountCategory,
    DiscountKind,
    TuitionDiscount,
)


class TuitionDiscountPort(Protocol):
    async def set_active(
        self, policy: TuitionDiscount, *, set_by: str
    ) -> TuitionDiscount: ...

    async def remove(self, enrollment_id: str, *, ended_by: str) -> None: ...


class SetTuitionDiscountCommand(BaseModel):
    model_config = {"frozen": True}

    discount_id: str
    enrollment_id: str
    student_id: str
    category: DiscountCategory
    category_label: str | None = None
    kind: DiscountKind
    percent_bps: int | None = None
    amount_off_cents: int | None = None
    fixed_net_cents: int | None = None
    effective_start: date
    effective_end: date | None = None
    note: str | None = None
    set_by: str


class SetTuitionDiscount:
    def __init__(self, *, discounts: TuitionDiscountPort) -> None:
        self._discounts = discounts

    async def execute(self, cmd: SetTuitionDiscountCommand) -> TuitionDiscount:
        policy = TuitionDiscount(
            discount_id=cmd.discount_id,
            enrollment_id=cmd.enrollment_id,
            student_id=cmd.student_id,
            category=cmd.category,
            category_label=cmd.category_label,
            kind=cmd.kind,
            percent_bps=cmd.percent_bps,
            amount_off_cents=cmd.amount_off_cents,
            fixed_net_cents=cmd.fixed_net_cents,
            effective_start=cmd.effective_start,
            effective_end=cmd.effective_end,
            note=cmd.note,
        )
        return await self._discounts.set_active(policy, set_by=cmd.set_by)


class RemoveTuitionDiscountCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    ended_by: str


class RemoveTuitionDiscount:
    def __init__(self, *, discounts: TuitionDiscountPort) -> None:
        self._discounts = discounts

    async def execute(self, cmd: RemoveTuitionDiscountCommand) -> None:
        await self._discounts.remove(cmd.enrollment_id, ended_by=cmd.ended_by)
