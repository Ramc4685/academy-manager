"""Admin manual payment operations inside Billing.

These preserve the legacy billing workflows while keeping the BFF thin:
monthly invoice generation, manual paid marks, discounts, and undo for
non-Stripe payments.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class GenerateMonthlyPaymentsCommand(BaseModel):
    model_config = {"frozen": True}
    period: str = Field(pattern=r"^\d{4}-\d{2}$")


class GenerateMonthlyPaymentsResult(BaseModel):
    model_config = {"frozen": True}
    created: int
    skipped_existing: int = 0
    skipped_no_charge: int = 0
    skipped_autopay: int = 0
    skipped_paused: int = 0


class MarkPaymentPaidCommand(BaseModel):
    model_config = {"frozen": True}
    payment_id: str
    payment_method: str = "cash"
    notes: str = ""


class ApplyPaymentDiscountCommand(BaseModel):
    model_config = {"frozen": True}
    payment_id: str
    discount_cents: int = Field(ge=0)


class UndoPaymentPaidCommand(BaseModel):
    model_config = {"frozen": True}
    payment_id: str


class AdminPaymentOperationsPort(Protocol):
    async def generate_monthly_payments(self, period: str) -> GenerateMonthlyPaymentsResult: ...
    async def mark_payment_paid(
        self, payment_id: str, *, payment_method: str, notes: str
    ) -> None: ...
    async def apply_payment_discount(self, payment_id: str, discount_cents: int) -> None: ...
    async def undo_payment_paid(self, payment_id: str) -> None: ...


class GenerateMonthlyPayments:
    def __init__(self, *, payments: AdminPaymentOperationsPort) -> None:
        self._payments = payments

    async def execute(self, cmd: GenerateMonthlyPaymentsCommand) -> GenerateMonthlyPaymentsResult:
        return await self._payments.generate_monthly_payments(cmd.period)


class MarkPaymentPaid:
    def __init__(self, *, payments: AdminPaymentOperationsPort) -> None:
        self._payments = payments

    async def execute(self, cmd: MarkPaymentPaidCommand) -> None:
        await self._payments.mark_payment_paid(
            cmd.payment_id,
            payment_method=cmd.payment_method,
            notes=cmd.notes,
        )


class ApplyPaymentDiscount:
    def __init__(self, *, payments: AdminPaymentOperationsPort) -> None:
        self._payments = payments

    async def execute(self, cmd: ApplyPaymentDiscountCommand) -> None:
        await self._payments.apply_payment_discount(cmd.payment_id, cmd.discount_cents)


class UndoPaymentPaid:
    def __init__(self, *, payments: AdminPaymentOperationsPort) -> None:
        self._payments = payments

    async def execute(self, cmd: UndoPaymentPaidCommand) -> None:
        await self._payments.undo_payment_paid(cmd.payment_id)
