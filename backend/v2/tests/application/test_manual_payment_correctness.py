"""Manual payment correctness for admin billing operations."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    ApplyPaymentDiscount,
    ApplyPaymentDiscountCommand,
    MarkPaymentPaid,
    MarkPaymentPaidCommand,
)


@dataclass
class CapturingPaymentOps:
    recorded: list[dict[str, object]] = field(default_factory=list)
    discounts: list[dict[str, object]] = field(default_factory=list)

    async def mark_payment_paid(
        self,
        payment_id: str,
        *,
        payment_method: str,
        notes: str,
        amount_received_cents: int | None,
        reference_number: str | None,
    ) -> None:
        self.recorded.append(
            {
                "payment_id": payment_id,
                "payment_method": payment_method,
                "notes": notes,
                "amount_received_cents": amount_received_cents,
                "reference_number": reference_number,
            }
        )

    async def apply_payment_discount(
        self,
        payment_id: str,
        discount_cents: int,
        *,
        reason: str,
    ) -> None:
        self.discounts.append(
            {
                "payment_id": payment_id,
                "discount_cents": discount_cents,
                "reason": reason,
            }
        )


@pytest.mark.asyncio
async def test_manual_payment_records_actual_amount_method_and_reference() -> None:
    ops = CapturingPaymentOps()
    use_case = MarkPaymentPaid(payments=ops)

    await use_case.execute(
        MarkPaymentPaidCommand(
            payment_id="pay-1",
            payment_method="zelle",
            amount_received_cents=4_000,
            reference_number="ZELLE-77",
            notes="Parent paid half at the desk",
        )
    )

    assert ops.recorded == [
        {
            "payment_id": "pay-1",
            "payment_method": "zelle",
            "notes": "Parent paid half at the desk",
            "amount_received_cents": 4_000,
            "reference_number": "ZELLE-77",
        }
    ]


@pytest.mark.parametrize(
    "method",
    ["cash", "check", "zelle", "venmo", "bank_transfer", "other"],
)
def test_manual_payment_accepts_supported_methods(method: str) -> None:
    cmd = MarkPaymentPaidCommand(payment_id="pay-1", payment_method=method)

    assert cmd.payment_method == method


def test_manual_payment_rejects_unsupported_methods() -> None:
    with pytest.raises(ValueError):
        MarkPaymentPaidCommand(payment_id="pay-1", payment_method="wire")


@pytest.mark.asyncio
async def test_discount_requires_amount_and_reason() -> None:
    ops = CapturingPaymentOps()
    use_case = ApplyPaymentDiscount(payments=ops)

    await use_case.execute(
        ApplyPaymentDiscountCommand(
            payment_id="pay-1",
            discount_cents=1_500,
            reason="Sibling discount",
        )
    )

    assert ops.discounts == [
        {
            "payment_id": "pay-1",
            "discount_cents": 1_500,
            "reason": "Sibling discount",
        }
    ]


def test_discount_rejects_missing_reason() -> None:
    with pytest.raises(ValueError):
        ApplyPaymentDiscountCommand(payment_id="pay-1", discount_cents=1_500, reason="")
