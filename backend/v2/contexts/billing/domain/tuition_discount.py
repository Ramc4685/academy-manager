"""Recurring tuition discount / waiver policy (billing bounded context).

This is the durable source of truth for a per-enrollment discount. It is projected
onto monthly ledger invoices by the payment repository (see
``infrastructure/mongo_payment_repo.py``). It is intentionally separate from the
onboarding legal/liability waiver flow — ``kind="waiver"`` here means *tuition zeroed*,
nothing to do with signatures.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, model_validator

DiscountCategory = Literal[
    "owner_child", "coach_child", "scholarship", "sibling", "other"
]
DiscountKind = Literal["waiver", "percent", "amount_off", "fixed_net"]
DiscountStatus = Literal["active", "superseded", "ended"]

_CATEGORY_LABELS: dict[str, str] = {
    "owner_child": "Owner child",
    "coach_child": "Coach child",
    "scholarship": "Scholarship",
    "sibling": "Sibling discount",
}


class TuitionDiscount(BaseModel):
    """A single, versioned discount policy for one enrollment.

    At most one row per enrollment is ``active`` at a time; edits supersede the
    prior active row (history retained).
    """

    model_config = {"frozen": True}

    discount_id: str
    academy_id: str | None = None
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
    status: DiscountStatus = "active"
    set_by: str | None = None
    set_at: datetime | None = None
    ended_by: str | None = None
    ended_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self) -> "TuitionDiscount":
        if self.category == "other" and not (self.category_label or "").strip():
            raise ValueError("category_label is required when category is 'other'")
        if self.kind == "percent":
            if self.percent_bps is None or not (0 < self.percent_bps <= 10000):
                raise ValueError("percent_bps must be in (0, 10000]")
        if self.kind == "amount_off" and (
            self.amount_off_cents is None or self.amount_off_cents < 0
        ):
            raise ValueError("amount_off_cents must be >= 0")
        if self.kind == "fixed_net" and (
            self.fixed_net_cents is None or self.fixed_net_cents < 0
        ):
            raise ValueError("fixed_net_cents must be >= 0")
        if self.effective_end is not None and self.effective_end < self.effective_start:
            raise ValueError("effective_end must be >= effective_start")
        return self


def monthly_discount_cents(
    policy: TuitionDiscount, *, monthly_price_cents: int
) -> int:
    """Discount expressed at monthly scale, floored into ``[0, monthly_price_cents]``.

    This value is fed into ``FirstMonthProrationPolicy.quote(discount_cents=...)``,
    which already subtracts it from the monthly price before prorating. Keeping the
    discount at monthly scale means the same number works for full and prorated months.
    """
    if policy.kind == "waiver":
        d = monthly_price_cents
    elif policy.kind == "percent":
        d = round(monthly_price_cents * (policy.percent_bps or 0) / 10000)
    elif policy.kind == "amount_off":
        d = min(policy.amount_off_cents or 0, monthly_price_cents)
    elif policy.kind == "fixed_net":
        d = max(monthly_price_cents - (policy.fixed_net_cents or 0), 0)
    else:  # pragma: no cover - exhaustive over DiscountKind
        d = 0
    return max(0, min(d, monthly_price_cents))


def display_label(policy: TuitionDiscount) -> str:
    """Human label for the badge / parent invoice line (never the private note)."""
    if policy.category == "other":
        return policy.category_label or "Discount"
    return _CATEGORY_LABELS[policy.category]
