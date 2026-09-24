"""Issue a refund — admin path.

Idempotent per refund REQUEST, not per refund shape (#930): the caller's
``idempotency_key`` identifies one attempt, scoped to the academy that owns the
payment. A retry of the same key replays; a new key is a new refund (or a loud
``RefundExceedsAmount``); a keyless identical repeat is a 409 to confirm. See
``billing/application/refund_idempotency.py`` for the full policy.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import (
    PaymentRepository,
    StripeGateway,
)
from backend.v2.contexts.billing.application.refund_idempotency import (
    refund_keys,
    remember,
    replay_or_reject,
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
from backend.v2.shared.idempotency import IdempotencyStore


class IssueRefundCommand(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    amount_cents: int | None = Field(default=None, ge=0)
    reason: str = "admin_initiated"
    #: One refund attempt. Admin routes forward the client's ``Idempotency-Key``;
    #: internal callers pass a deterministic key for the one refund they own
    #: (e.g. the capacity auto-refund of a payment). None = keyless: an
    #: identical repeat inside the TTL is rejected, never replayed.
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


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

    async def execute(self, cmd: IssueRefundCommand) -> IssueRefundResult:
        # Tenant-scoped read FIRST: another academy's payment id is a plain
        # "not found" and never reaches (or learns about) a cached result.
        payment = await self._payments.get(cmd.payment_id)
        if payment is None:
            raise PaymentNotFound("no such payment", payment_id=cmd.payment_id)
        keys = refund_keys(
            kind="payment_refund",
            academy_id=payment.academy_id,
            target_id=payment.payment_id,
            amount_cents=cmd.amount_cents,
            reason=cmd.reason,
            idempotency_key=cmd.idempotency_key,
        )
        cached = await replay_or_reject(self._idempotency_store, keys)
        if cached is not None:
            return IssueRefundResult.model_validate(cached)
        if not payment.stripe_payment_intent_id:
            raise RefundFailed("payment has no Stripe payment intent")

        amount = (
            cmd.amount_cents
            if cmd.amount_cents is not None
            else payment.amount_cents - payment.refunded_cents
        )
        if payment.refunded_cents + amount > payment.amount_cents:
            raise RefundExceedsAmount(
                "refund exceeds payment amount",
                payment_amount=payment.amount_cents,
                already_refunded=payment.refunded_cents,
                requested=amount,
            )
        try:
            refund_id = await self._stripe.issue_refund(
                payment.stripe_payment_intent_id,
                amount_cents=amount,
                idempotency_key=keys.stripe_key,
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
        result = IssueRefundResult(
            payment_id=updated.payment_id,
            stripe_refund_id=refund_id,
            refunded_cents=amount,
            total_refunded_cents=new_total,
        )
        stored = await remember(self._idempotency_store, keys, result.model_dump(mode="json"))
        return IssueRefundResult.model_validate(stored)


def _normalize_reason(reason: str) -> str:
    valid = {
        "admin_initiated",
        "capacity_failed",
        "registration_declined",
        "duplicate",
        "other",
    }
    return reason if reason in valid else "other"
