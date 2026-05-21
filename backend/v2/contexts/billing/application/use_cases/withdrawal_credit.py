"""Early withdrawal credit workflows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from backend.v2.shared.ids import new_ulid

from backend.v2.contexts.billing.application.ports import (
    CreditLedgerRepository,
    StripeGateway,
    SubscriptionRepository,
)
from backend.v2.contexts.billing.domain.credits import (
    EarlyWithdrawalCreditPolicy,
    WithdrawalCreditPreview,
)
from backend.v2.contexts.billing.domain.errors import PaymentNotFound
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry, Payment
from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot


class WithdrawalPaymentRepository(Protocol):
    async def latest_paid_payment_for_enrollment(self, enrollment_id: str) -> Payment | None: ...
    async def get_snapshot(self, snapshot_id: str) -> BillingCalculationSnapshot | None: ...


class WithdrawalEnrollmentRepository(Protocol):
    async def get(self, enrollment_id: str): ...
    async def mark_withdrawn(
        self, enrollment_id: str, *, withdrawal_date: datetime
    ) -> None: ...


class PreviewWithdrawalCreditCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    withdrawal_date: datetime
    actor_id: str


class WithdrawalCreditPreviewResult(BaseModel):
    model_config = {"frozen": True}

    credit_amount_cents: int
    paid_tuition_cents: int
    refunded_tuition_cents: int
    net_paid_tuition_cents: int
    unused_eligible_classes: int
    paid_period_eligible_classes: int
    formula: str
    no_credit_reason: str | None = None


class ApproveWithdrawalCreditCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    withdrawal_date: datetime
    actor_id: str
    admin_note: str = ""
    cancel_subscription_immediately: bool = False


class ApproveWithdrawalCreditResult(BaseModel):
    model_config = {"frozen": True}

    status: str
    credit_amount_cents: int
    credit_balance_cents: int
    credit_id: str | None = None
    no_credit_reason: str | None = None


class PreviewWithdrawalCredit:
    def __init__(
        self,
        *,
        payments: WithdrawalPaymentRepository,
        enrollments: WithdrawalEnrollmentRepository,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._payments = payments
        self._enrollments = enrollments
        self._clock = clock

    async def execute(
        self, cmd: PreviewWithdrawalCreditCommand
    ) -> WithdrawalCreditPreviewResult:
        enrollment = await self._enrollments.get(cmd.enrollment_id)
        if enrollment is None:
            raise PaymentNotFound("enrollment not found", enrollment_id=cmd.enrollment_id)
        payment, snapshot = await _paid_payment_and_snapshot(self._payments, cmd.enrollment_id)
        preview = _preview_from_snapshot(
            payment=payment,
            snapshot=snapshot,
            withdrawal_date=cmd.withdrawal_date,
            calculated_at=self._clock(),
            calculated_by=cmd.actor_id,
        )
        return _preview_result(preview)


class ApproveWithdrawalCredit:
    def __init__(
        self,
        *,
        payments: WithdrawalPaymentRepository,
        credits: CreditLedgerRepository,
        enrollments: WithdrawalEnrollmentRepository,
        subscriptions: SubscriptionRepository,
        stripe: StripeGateway,
        academy_id: str,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._payments = payments
        self._credits = credits
        self._enrollments = enrollments
        self._subscriptions = subscriptions
        self._stripe = stripe
        self._academy_id = academy_id
        self._clock = clock

    async def execute(
        self, cmd: ApproveWithdrawalCreditCommand
    ) -> ApproveWithdrawalCreditResult:
        enrollment = await self._enrollments.get(cmd.enrollment_id)
        if enrollment is None:
            raise PaymentNotFound("enrollment not found", enrollment_id=cmd.enrollment_id)

        # Idempotency: if a previous approval already created an APPROVED
        # EARLY_WITHDRAWAL_CREDIT for this enrollment, return it instead of
        # creating a duplicate. Retries, double-click submissions, or repeated
        # admin actions therefore do not inflate the parent's credit balance.
        existing = await self._credits.find_active_for_enrollment(
            enrollment_id=cmd.enrollment_id, type="EARLY_WITHDRAWAL_CREDIT"
        )
        if existing is not None:
            balance = await self._credits.balance_for_parent(existing.parent_id)
            return ApproveWithdrawalCreditResult(
                status="APPROVED",
                credit_amount_cents=existing.amount_cents,
                credit_balance_cents=balance,
                credit_id=existing.credit_id,
                no_credit_reason=None,
            )

        payment, snapshot = await _paid_payment_and_snapshot(self._payments, cmd.enrollment_id)
        now = self._clock()
        preview = _preview_from_snapshot(
            payment=payment,
            snapshot=snapshot,
            withdrawal_date=cmd.withdrawal_date,
            calculated_at=now,
            calculated_by=cmd.actor_id,
        )

        credit_id: str | None = None
        if preview.credit_amount_cents > 0:
            credit_id = str(new_ulid())
            await self._credits.create(
                CreditLedgerEntry(
                    credit_id=credit_id,
                    academy_id=self._academy_id,
                    parent_id=payment.parent_id,
                    student_id=enrollment.student_id,
                    enrollment_id=enrollment.enrollment_id,
                    type="EARLY_WITHDRAWAL_CREDIT",
                    status="APPROVED",
                    amount_cents=preview.credit_amount_cents,
                    remaining_amount_cents=preview.credit_amount_cents,
                    currency=payment.currency,
                    reason=cmd.admin_note or "Early withdrawal",
                    calculation_snapshot_id=snapshot.snapshot_id,
                    approved_by=cmd.actor_id,
                    approved_at=now,
                    expires_at=now + timedelta(days=365),
                    created_at=now,
                    updated_at=now,
                )
            )

        await self._enrollments.mark_withdrawn(
            enrollment.enrollment_id,
            withdrawal_date=cmd.withdrawal_date,
        )
        subscription = await self._subscriptions.latest_for_enrollment(enrollment.enrollment_id)
        if subscription is not None and subscription.stripe_subscription_id:
            at_period_end = not cmd.cancel_subscription_immediately
            await self._stripe.cancel_subscription(
                subscription.stripe_subscription_id,
                at_period_end=at_period_end,
            )
            await self._subscriptions.save(
                subscription.model_copy(
                    update={"status": "cancelled", "updated_at": now}
                )
            )

        balance = await self._credits.balance_for_parent(payment.parent_id)
        return ApproveWithdrawalCreditResult(
            status="APPROVED" if credit_id else "NO_CREDIT",
            credit_amount_cents=preview.credit_amount_cents,
            credit_balance_cents=balance,
            credit_id=credit_id,
            no_credit_reason=preview.no_credit_reason,
        )


async def _paid_payment_and_snapshot(
    payments: WithdrawalPaymentRepository,
    enrollment_id: str,
) -> tuple[Payment, BillingCalculationSnapshot]:
    payment = await payments.latest_paid_payment_for_enrollment(enrollment_id)
    if payment is None or not payment.calculation_snapshot_id:
        raise PaymentNotFound("paid payment snapshot not found", enrollment_id=enrollment_id)
    snapshot = await payments.get_snapshot(payment.calculation_snapshot_id)
    if snapshot is None:
        raise PaymentNotFound(
            "billing calculation snapshot not found",
            payment_id=payment.payment_id,
            calculation_snapshot_id=payment.calculation_snapshot_id,
        )
    return payment, snapshot


def _preview_from_snapshot(
    *,
    payment: Payment,
    snapshot: BillingCalculationSnapshot,
    withdrawal_date: datetime,
    calculated_at: datetime,
    calculated_by: str,
) -> WithdrawalCreditPreview:
    paid_period_classes = snapshot.billable_remaining_classes
    unused = _unused_included_occurrences(snapshot, withdrawal_date)
    return EarlyWithdrawalCreditPolicy().preview(
        paid_tuition_cents=payment.amount_cents,
        refunded_tuition_cents=payment.refunded_cents,
        unused_eligible_classes=unused,
        paid_period_eligible_classes=paid_period_classes,
        calculated_at=calculated_at,
        calculated_by=calculated_by,
    )


def _unused_included_occurrences(
    snapshot: BillingCalculationSnapshot,
    withdrawal_date: datetime,
) -> int:
    withdrawal = (
        withdrawal_date
        if withdrawal_date.tzinfo
        else withdrawal_date.replace(tzinfo=timezone.utc)
    )
    tz = ZoneInfo(snapshot.timezone)
    count = 0
    for occurrence_id in snapshot.included_occurrence_ids:
        local_start = _local_start_from_occurrence_id(occurrence_id, tz)
        if local_start is not None and local_start.astimezone(timezone.utc) > withdrawal:
            count += 1
    return count


def _local_start_from_occurrence_id(occurrence_id: str, tz: ZoneInfo) -> datetime | None:
    parts = occurrence_id.split(":")
    if len(parts) < 4:
        return None
    local_date = parts[-3]
    local_time = f"{parts[-2]}:{parts[-1]}"
    try:
        return datetime.fromisoformat(f"{local_date}T{local_time}").replace(tzinfo=tz)
    except ValueError:
        return None


def _preview_result(preview: WithdrawalCreditPreview) -> WithdrawalCreditPreviewResult:
    return WithdrawalCreditPreviewResult(
        credit_amount_cents=preview.credit_amount_cents,
        paid_tuition_cents=preview.paid_tuition_cents,
        refunded_tuition_cents=preview.refunded_tuition_cents,
        net_paid_tuition_cents=preview.net_paid_tuition_cents,
        unused_eligible_classes=preview.unused_eligible_classes,
        paid_period_eligible_classes=preview.paid_period_eligible_classes,
        formula=preview.formula,
        no_credit_reason=preview.no_credit_reason,
    )
