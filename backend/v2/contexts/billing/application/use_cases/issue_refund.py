"""Issue a refund — admin path.

Idempotent on payment_id + amount via the @idempotent decorator (so the
admin double-clicking the refund button doesn't double-refund).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import (
    PaymentRepository,
    StripeGateway,
)
from backend.v2.contexts.billing.domain.errors import (
    PaymentNotFound,
    RefundExceedsAmount,
    RefundFailed,
)
from backend.v2.contexts.billing.domain.events import (
    PaymentRefunded,
    PaymentRefundedPayload,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore, idempotent


class IssueRefundCommand(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    amount_cents: int | None = Field(default=None, ge=0)
    reason: str = "admin_initiated"


class IssueRefundResult(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    stripe_refund_id: str
    refunded_cents: int
    total_refunded_cents: int


class IssueRefund:
    def __init__(
        self,
        *,
        payment_repo: PaymentRepository,
        stripe: StripeGateway,
        outbox: Outbox,
        idempotency_store: IdempotencyStore,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._payments = payment_repo
        self._stripe = stripe
        self._outbox = outbox
        self._idempotency_store = idempotency_store
        self._now = clock

    @idempotent(
        key_from=lambda self, cmd: f"refund:{cmd.payment_id}:{cmd.amount_cents}:{cmd.reason}",
        result_type=IssueRefundResult,
    )
    async def execute(self, cmd: IssueRefundCommand) -> IssueRefundResult:
        payment = await self._payments.get(cmd.payment_id)
        if payment is None:
            raise PaymentNotFound("no such payment", payment_id=cmd.payment_id)
        if not payment.stripe_payment_intent_id:
            raise RefundFailed("payment has no Stripe payment intent")

        amount = cmd.amount_cents if cmd.amount_cents is not None else payment.amount_cents - payment.refunded_cents
        if payment.refunded_cents + amount > payment.amount_cents:
            raise RefundExceedsAmount(
                "refund exceeds payment amount",
                payment_amount=payment.amount_cents,
                already_refunded=payment.refunded_cents,
                requested=amount,
            )
        try:
            refund_id = await self._stripe.issue_refund(
                payment.stripe_payment_intent_id, amount_cents=amount
            )
        except Exception as exc:
            raise RefundFailed(str(exc)) from exc

        new_total = payment.refunded_cents + amount
        new_status = "refunded" if new_total >= payment.amount_cents else "partially_refunded"
        updated = payment.model_copy(
            update={
                "status": new_status,
                "refunded_cents": new_total,
                "updated_at": self._now(),
            }
        )
        await self._payments.save(updated)
        await self._outbox.append(
            PaymentRefunded(
                aggregate_id=updated.payment_id,
                academy_id=updated.academy_id,
                payload=PaymentRefundedPayload(
                    payment_id=updated.payment_id,
                    refunded_cents=amount,
                    total_refunded_cents=new_total,
                    reason=_normalize_reason(cmd.reason),
                ),
            )
        )
        return IssueRefundResult(
            payment_id=updated.payment_id,
            stripe_refund_id=refund_id,
            refunded_cents=amount,
            total_refunded_cents=new_total,
        )


def _normalize_reason(reason: str) -> str:
    valid = {"admin_initiated", "capacity_failed", "duplicate", "other"}
    return reason if reason in valid else "other"
