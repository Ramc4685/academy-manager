"""Admin manual payment operations inside Billing.

These preserve the legacy billing workflows while keeping the BFF thin:
monthly invoice generation, manual paid marks, discounts, and undo for
non-Stripe payments.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

ManualPaymentMethod = Literal["cash", "check", "zelle", "venmo", "bank_transfer", "other"]


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
    payment_method: ManualPaymentMethod = "cash"
    amount_received_cents: int | None = Field(default=None, gt=0)
    reference_number: str | None = None
    notes: str = ""


class ApplyPaymentDiscountCommand(BaseModel):
    model_config = {"frozen": True}
    payment_id: str
    discount_cents: int = Field(ge=0)
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("discount reason is required")
        return value


class UndoPaymentPaidCommand(BaseModel):
    model_config = {"frozen": True}
    payment_id: str


class AdminPaymentOperationsPort(Protocol):
    async def generate_monthly_payments(self, period: str) -> GenerateMonthlyPaymentsResult: ...
    async def mark_payment_paid(
        self,
        payment_id: str,
        *,
        payment_method: str,
        notes: str,
        amount_received_cents: int | None,
        reference_number: str | None,
    ) -> None: ...
    async def apply_payment_discount(
        self, payment_id: str, discount_cents: int, *, reason: str
    ) -> None: ...
    async def undo_payment_paid(self, payment_id: str) -> None: ...


class DuesReminderSenderPort(Protocol):
    async def send_dues_reminders(
        self,
        *,
        parent_ids: list[str] | None,
        generate_invoice_artifacts: bool,
    ) -> dict[str, object]: ...


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
            amount_received_cents=cmd.amount_received_cents,
            reference_number=cmd.reference_number,
        )


class ApplyPaymentDiscount:
    def __init__(self, *, payments: AdminPaymentOperationsPort) -> None:
        self._payments = payments

    async def execute(self, cmd: ApplyPaymentDiscountCommand) -> None:
        await self._payments.apply_payment_discount(
            cmd.payment_id,
            cmd.discount_cents,
            reason=cmd.reason,
        )


class UndoPaymentPaid:
    def __init__(self, *, payments: AdminPaymentOperationsPort) -> None:
        self._payments = payments

    async def execute(self, cmd: UndoPaymentPaidCommand) -> None:
        await self._payments.undo_payment_paid(cmd.payment_id)


class SendDuesRemindersCommand(BaseModel):
    model_config = {"frozen": True}
    parent_ids: list[str] | None = None
    generate_invoice_artifacts: bool = True


class SendDuesReminders:
    def __init__(self, *, sender: DuesReminderSenderPort) -> None:
        self._sender = sender

    async def execute(self, cmd: SendDuesRemindersCommand) -> dict[str, object]:
        parent_ids = list(dict.fromkeys(cmd.parent_ids or [])) or None
        return await self._sender.send_dues_reminders(
            parent_ids=parent_ids,
            generate_invoice_artifacts=cmd.generate_invoice_artifacts,
        )
