"""Account credit domain policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


class WithdrawalCreditPreview(BaseModel):
    credit_amount_cents: int
    paid_tuition_cents: int
    refunded_tuition_cents: int
    net_paid_tuition_cents: int
    unused_eligible_classes: int
    paid_period_eligible_classes: int
    formula: str
    rounding_mode: str = "HALF_UP_FINAL_CENT"
    no_credit_reason: str | None = None
    calculated_at: datetime
    calculated_by: str


@dataclass(frozen=True)
class EarlyWithdrawalCreditPolicy:
    def preview(
        self,
        *,
        paid_tuition_cents: int,
        refunded_tuition_cents: int,
        unused_eligible_classes: int,
        paid_period_eligible_classes: int,
        calculated_at: datetime,
        calculated_by: str,
    ) -> WithdrawalCreditPreview:
        net_paid = max(paid_tuition_cents - refunded_tuition_cents, 0)
        formula = (
            f"max({paid_tuition_cents} - {refunded_tuition_cents}, 0) "
            f"* {unused_eligible_classes} / {paid_period_eligible_classes}"
        )
        if paid_period_eligible_classes == 0:
            return WithdrawalCreditPreview(
                credit_amount_cents=0,
                paid_tuition_cents=paid_tuition_cents,
                refunded_tuition_cents=refunded_tuition_cents,
                net_paid_tuition_cents=net_paid,
                unused_eligible_classes=unused_eligible_classes,
                paid_period_eligible_classes=paid_period_eligible_classes,
                formula=formula,
                no_credit_reason="NO_PAID_PERIOD_ELIGIBLE_CLASSES",
                calculated_at=calculated_at,
                calculated_by=calculated_by,
            )
        amount = _round_half_up_rational(
            net_paid * unused_eligible_classes, paid_period_eligible_classes
        )
        reason = "ZERO_UNUSED_CLASSES" if unused_eligible_classes == 0 else None
        if amount == 0 and reason is None:
            reason = "ZERO_NET_PAID_TUITION"
        return WithdrawalCreditPreview(
            credit_amount_cents=amount,
            paid_tuition_cents=paid_tuition_cents,
            refunded_tuition_cents=refunded_tuition_cents,
            net_paid_tuition_cents=net_paid,
            unused_eligible_classes=unused_eligible_classes,
            paid_period_eligible_classes=paid_period_eligible_classes,
            formula=formula,
            no_credit_reason=reason,
            calculated_at=calculated_at,
            calculated_by=calculated_by,
        )


def _round_half_up_rational(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    quotient, remainder = divmod(numerator, denominator)
    return quotient + (1 if remainder * 2 >= denominator else 0)
