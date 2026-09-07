"""Early withdrawal credit workflows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel

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
from backend.v2.shared.ids import new_ulid


class WithdrawalPaymentRepository(Protocol):
    async def latest_paid_payment_for_enrollment(self, enrollment_id: str) -> Payment | None: ...
    async def get_snapshot(self, snapshot_id: str) -> BillingCalculationSnapshot | None: ...


class WithdrawalEnrollmentRepository(Protocol):
    async def get(self, enrollment_id: str): ...


#: Mirrors ``enrollment.application.ports.WithdrawalOutcome`` (billing may not
#: import enrollment; composition bridges the two identical literals).
WithdrawalOutcome = Literal["credit", "refund", "adjustment"]


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


class RecordWithdrawalDecisionCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    academy_id: str
    student_id: str | None = None
    outcome: WithdrawalOutcome
    withdrawal_date: datetime
    actor_id: str
    reason: str = ""


class WithdrawalDecisionResult(BaseModel):
    """What billing actually did for one withdrawal (issue #670).

    ``billing_result`` vocabulary, copied verbatim onto the lifecycle event:

    * ``credit_approved`` — a new EARLY_WITHDRAWAL_CREDIT ledger entry
    * ``credit_already_approved`` — an earlier run made it; nothing new issued
    * ``credit_none`` — the policy computed zero (``no_credit_reason`` says why)
    * ``refund_manual`` / ``adjustment_manual`` — nothing automated happens;
      the owner settles it by hand from the invoice/refund screens
    """

    model_config = {"frozen": True}

    billing_policy: str
    billing_result: str
    credit_id: str | None = None
    credit_amount_cents: int = 0
    credit_balance_cents: int = 0
    no_credit_reason: str | None = None
    metadata: dict[str, str]


class PreviewWithdrawalCredit:
    def __init__(
        self,
        *,
        payments: WithdrawalPaymentRepository,
        enrollments: WithdrawalEnrollmentRepository,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._payments = payments
        self._enrollments = enrollments
        self._clock = clock

    async def execute(self, cmd: PreviewWithdrawalCreditCommand) -> WithdrawalCreditPreviewResult:
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


class RecordWithdrawalDecision:
    """Billing-side step of a withdrawal, invoked BY ``WithdrawEnrollment``
    (issue #670). Owns no lifecycle state: it never touches the enrollment
    row, the seat, the roster or the lifecycle event.

    For ``credit`` it is idempotent on the ledger — an APPROVED
    EARLY_WITHDRAWAL_CREDIT for the enrollment is returned, never duplicated,
    so a retried withdraw cannot inflate the parent's balance — and it
    cancels the legacy Stripe subscription at period end exactly once.
    """

    def __init__(
        self,
        *,
        payments: WithdrawalPaymentRepository,
        credits: CreditLedgerRepository,
        subscriptions: SubscriptionRepository,
        stripe: StripeGateway,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._payments = payments
        self._credits = credits
        self._subscriptions = subscriptions
        self._stripe = stripe
        self._clock = clock

    async def execute(self, cmd: RecordWithdrawalDecisionCommand) -> WithdrawalDecisionResult:
        if cmd.outcome != "credit":
            # Honest: no refund or adjustment is automated here. The owner
            # issues it from the invoice / refund screens; the event says so.
            return WithdrawalDecisionResult(
                billing_policy=f"withdrawal_{cmd.outcome}",
                billing_result=f"{cmd.outcome}_manual",
                metadata={"outcome": cmd.outcome, "automation": "none"},
            )

        existing = await self._credits.find_active_for_enrollment(
            enrollment_id=cmd.enrollment_id,
            type="EARLY_WITHDRAWAL_CREDIT",
        )
        if existing is not None:
            balance = await self._credits.balance_for_parent(existing.parent_id)
            return WithdrawalDecisionResult(
                billing_policy="early_withdrawal_credit",
                billing_result="credit_already_approved",
                credit_id=existing.credit_id,
                credit_amount_cents=existing.amount_cents,
                credit_balance_cents=balance,
                metadata={
                    "outcome": "credit",
                    "credit_amount_cents": str(existing.amount_cents),
                },
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
                    academy_id=cmd.academy_id,
                    parent_id=payment.parent_id,
                    student_id=cmd.student_id,
                    enrollment_id=cmd.enrollment_id,
                    type="EARLY_WITHDRAWAL_CREDIT",
                    status="APPROVED",
                    amount_cents=preview.credit_amount_cents,
                    remaining_amount_cents=preview.credit_amount_cents,
                    currency=payment.currency,
                    reason=cmd.reason or "Early withdrawal",
                    calculation_snapshot_id=payment.calculation_snapshot_id,
                    approved_by=cmd.actor_id,
                    approved_at=now,
                    expires_at=now + timedelta(days=365),
                    created_at=now,
                    updated_at=now,
                )
            )
        subscription_result = await self._cancel_legacy_subscription(cmd.enrollment_id, now)
        balance = await self._credits.balance_for_parent(payment.parent_id)
        metadata = {
            "outcome": "credit",
            "credit_amount_cents": str(preview.credit_amount_cents),
            "subscription": subscription_result,
        }
        if preview.no_credit_reason:
            metadata["no_credit_reason"] = preview.no_credit_reason
        return WithdrawalDecisionResult(
            billing_policy="early_withdrawal_credit",
            billing_result="credit_approved" if credit_id else "credit_none",
            credit_id=credit_id,
            credit_amount_cents=preview.credit_amount_cents,
            credit_balance_cents=balance,
            no_credit_reason=preview.no_credit_reason,
            metadata=metadata,
        )

    async def _cancel_legacy_subscription(self, enrollment_id: str, now: datetime) -> str:
        subscription = await self._subscriptions.latest_for_enrollment(enrollment_id)
        if subscription is None or not subscription.stripe_subscription_id:
            return "none"
        if subscription.status == "cancelled":
            return "already_cancelled"
        await self._stripe.cancel_subscription(
            subscription.stripe_subscription_id,
            at_period_end=True,
        )
        await self._subscriptions.save(
            subscription.model_copy(update={"status": "cancelled", "updated_at": now})
        )
        return "cancelled_at_period_end"


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
    withdrawal = withdrawal_date if withdrawal_date.tzinfo else withdrawal_date.replace(tzinfo=UTC)
    tz = ZoneInfo(snapshot.timezone)
    count = 0
    for occurrence_id in snapshot.included_occurrence_ids:
        local_start = _local_start_from_occurrence_id(occurrence_id, tz)
        if local_start is not None and local_start.astimezone(UTC) > withdrawal:
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
