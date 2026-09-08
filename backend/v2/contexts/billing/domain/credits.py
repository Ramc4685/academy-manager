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


#: ``source_type`` stamped on every class-cancellation credit. Together with
#: ``source_id`` (``"<occurrence_id>:<enrollment_id>"``) it is the idempotency
#: key: migration 0168 makes the pair unique per academy, so a retried cancel
#: can never credit the same family twice for the same date.
CLASS_CANCELLATION_SOURCE_TYPE = "occurrence_cancellation"


def class_cancellation_source_id(*, occurrence_id: str, enrollment_id: str) -> str:
    return f"{occurrence_id}:{enrollment_id}"


def class_cancellation_credit_cents(*, period_charge_cents: int, billable_classes: int) -> int:
    """One cancelled date's share of what the family was (or will be) charged
    for the month (issue #671).

    ``period_charge_cents`` is the tuition the family owes for the period
    before any account credit — the invoice's subtotal net of tuition discount
    when it exists, else the monthly price net of discount. ``billable_classes``
    is how many classes that charge bought, INCLUDING the one being cancelled.
    Half-up rounding on the final cent, like every other tuition split here.
    """
    if period_charge_cents <= 0 or billable_classes <= 0:
        return 0
    return _round_half_up_rational(period_charge_cents, billable_classes)


def _round_half_up_rational(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    quotient, remainder = divmod(numerator, denominator)
    return quotient + (1 if remainder * 2 >= denominator else 0)
