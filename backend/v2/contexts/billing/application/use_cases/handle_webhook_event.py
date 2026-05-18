"""Stripe webhook handler.

Verifies signature (via gateway), idempotently claims the event id, and
dispatches to per-event-type handlers. Each transition emits a domain
event into the outbox so cross-context handlers (Enrollment confirm,
auto-refund, comms) can react asynchronously.

Mirrors the legacy state machine documented in the Wave-2 research
artifact, but encapsulates each transition in a use case so tests cover
each case in isolation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ulid import ULID

from backend.v2.contexts.billing.application.ports import (
    PaymentRepository,
    StripeEventDedup,
    StripeGateway,
    SubscriptionRepository,
)
from backend.v2.contexts.billing.domain.errors import InvalidWebhookSignature
from backend.v2.contexts.billing.domain.events import (
    CheckoutExpired,
    CheckoutExpiredPayload,
    PaymentFailed,
    PaymentFailedPayload,
    PaymentRefunded,
    PaymentRefundedPayload,
    PaymentSucceeded,
    PaymentSucceededPayload,
    SubscriptionUpdated,
    SubscriptionUpdatedPayload,
)
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.shared.events import Outbox
from backend.v2.shared.tenancy import tenant_scope

log = logging.getLogger(__name__)


class HandleWebhookEvent:
    def __init__(
        self,
        *,
        stripe: StripeGateway,
        dedup: StripeEventDedup,
        payments: PaymentRepository,
        subscriptions: SubscriptionRepository,
        outbox: Outbox,
        academy_id: str,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._stripe = stripe
        self._dedup = dedup
        self._payments = payments
        self._subscriptions = subscriptions
        self._outbox = outbox
        self._academy_id = academy_id
        self._now = clock

    async def execute(self, payload: bytes, signature: str) -> dict[str, Any]:
        try:
            event = self._stripe.verify_webhook(payload, signature)
        except Exception as exc:
            raise InvalidWebhookSignature(str(exc)) from exc

        event_id = str(event.get("id", ""))
        event_type = str(event.get("type", ""))
        if not event_id or not event_type:
            raise InvalidWebhookSignature("event missing id or type")

        with tenant_scope(self._academy_id):
            claimed = await self._dedup.claim(event_id, event_type)
            if not claimed:
                log.info("stripe_webhook_deduped event_id=%s", event_id)
                return {"received": True, "deduped": True}

            try:
                await self._dispatch(event_type, event)
                await self._dedup.mark_processed(event_id)
                return {"received": True, "type": event_type}
            except Exception as exc:
                await self._dedup.mark_failed(event_id, str(exc))
                raise

    async def _dispatch(self, event_type: str, event: dict[str, Any]) -> None:
        if event_type == "checkout.session.completed":
            await self._on_checkout_completed(event)
        elif event_type == "checkout.session.expired":
            await self._on_checkout_expired(event)
        elif event_type == "payment_intent.payment_failed":
            await self._on_payment_failed(event)
        elif event_type == "invoice.paid":
            await self._on_invoice_paid(event)
        elif event_type == "invoice.payment_failed":
            await self._on_invoice_payment_failed(event)
        elif event_type == "charge.refunded":
            await self._on_charge_refunded(event)
        elif event_type in (
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            await self._on_subscription_changed(event)
        else:
            log.info("stripe_webhook_ignored type=%s", event_type)

    async def _on_checkout_completed(self, event: dict[str, Any]) -> None:
        obj = event["data"]["object"]
        checkout_id = obj["id"]
        payment = await self._payments.get_by_checkout_session(checkout_id)
        if payment is None:
            log.warning("checkout.completed for unknown checkout_id=%s", checkout_id)
            return
        if payment.status == "succeeded":
            return  # already processed
        updated = payment.model_copy(
            update={
                "status": "succeeded",
                "stripe_payment_intent_id": obj.get("payment_intent"),
                "updated_at": self._now(),
            }
        )
        await self._payments.save(updated)
        await self._outbox.append(
            PaymentSucceeded(
                aggregate_id=updated.payment_id,
                academy_id=updated.academy_id,
                payload=PaymentSucceededPayload(
                    payment_id=updated.payment_id,
                    parent_id=updated.parent_id,
                    session_id=updated.session_id,
                    amount_cents=updated.amount_cents,
                    currency=updated.currency,
                    succeeded_at=updated.updated_at,
                ),
            )
        )

    async def _on_checkout_expired(self, event: dict[str, Any]) -> None:
        obj = event["data"]["object"]
        checkout_id = obj["id"]
        payment = await self._payments.get_by_checkout_session(checkout_id)
        if payment is None or payment.status not in ("pending",):
            return
        updated = payment.model_copy(update={"status": "expired", "updated_at": self._now()})
        await self._payments.save(updated)
        await self._outbox.append(
            CheckoutExpired(
                aggregate_id=updated.payment_id,
                academy_id=updated.academy_id,
                payload=CheckoutExpiredPayload(
                    payment_id=updated.payment_id,
                    parent_id=updated.parent_id,
                    session_id=updated.session_id,
                ),
            )
        )

    async def _on_payment_failed(self, event: dict[str, Any]) -> None:
        pi = event["data"]["object"]
        pi_id = pi["id"]
        payment = await self._payments.get_by_stripe_pi(pi_id)
        if payment is None:
            return
        updated = payment.model_copy(update={"status": "failed", "updated_at": self._now()})
        await self._payments.save(updated)
        await self._outbox.append(
            PaymentFailed(
                aggregate_id=updated.payment_id,
                academy_id=updated.academy_id,
                payload=PaymentFailedPayload(
                    payment_id=updated.payment_id,
                    parent_id=updated.parent_id,
                    session_id=updated.session_id,
                    reason=str(pi.get("last_payment_error", {}).get("message", "unknown")),
                ),
            )
        )

    async def _on_invoice_paid(self, event: dict[str, Any]) -> None:
        invoice = event["data"]["object"]
        payment = await self._payment_from_invoice(invoice, status="succeeded")
        if payment is None:
            return
        await self._payments.save(payment)
        await self._outbox.append(
            PaymentSucceeded(
                aggregate_id=payment.payment_id,
                academy_id=payment.academy_id,
                payload=PaymentSucceededPayload(
                    payment_id=payment.payment_id,
                    parent_id=payment.parent_id,
                    session_id=payment.session_id,
                    amount_cents=payment.amount_cents,
                    currency=payment.currency,
                    succeeded_at=payment.updated_at,
                ),
            )
        )

    async def _on_invoice_payment_failed(self, event: dict[str, Any]) -> None:
        invoice = event["data"]["object"]
        payment = await self._payment_from_invoice(invoice, status="failed")
        if payment is None:
            return
        await self._payments.save(payment)
        await self._outbox.append(
            PaymentFailed(
                aggregate_id=payment.payment_id,
                academy_id=payment.academy_id,
                payload=PaymentFailedPayload(
                    payment_id=payment.payment_id,
                    parent_id=payment.parent_id,
                    session_id=payment.session_id,
                    reason=str(invoice.get("last_finalization_error", {}).get("message", "invoice payment failed")),
                ),
            )
        )

    async def _on_charge_refunded(self, event: dict[str, Any]) -> None:
        ch = event["data"]["object"]
        pi_id = ch.get("payment_intent")
        if not pi_id:
            return
        payment = await self._payments.get_by_stripe_pi(pi_id)
        if payment is None:
            return
        total_refunded = int(ch.get("amount_refunded", 0))
        if total_refunded == 0 or total_refunded == payment.refunded_cents:
            return
        delta = max(0, total_refunded - payment.refunded_cents)
        new_status = "refunded" if total_refunded >= payment.amount_cents else "partially_refunded"
        updated = payment.model_copy(
            update={
                "status": new_status,
                "refunded_cents": total_refunded,
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
                    refunded_cents=delta,
                    total_refunded_cents=total_refunded,
                    reason="admin_initiated",
                ),
            )
        )

    async def _on_subscription_changed(self, event: dict[str, Any]) -> None:
        sub = event["data"]["object"]
        stripe_sub_id = sub["id"]
        existing = await self._subscriptions.get_by_stripe_sub(stripe_sub_id)
        if existing is None:
            return
        status = self._normalize_status(sub.get("status", "incomplete"))
        updated = existing.model_copy(update={"status": status, "updated_at": self._now()})
        await self._subscriptions.save(updated)
        await self._outbox.append(
            SubscriptionUpdated(
                aggregate_id=updated.subscription_id,
                academy_id=updated.academy_id,
                payload=SubscriptionUpdatedPayload(
                    subscription_id=updated.subscription_id,
                    parent_id=updated.parent_id,
                    status=status,
                ),
            )
        )

    @staticmethod
    def _normalize_status(stripe_status: str) -> str:
        mapping = {
            "active": "active",
            "trialing": "active",
            "past_due": "past_due",
            "canceled": "cancelled",
            "unpaid": "past_due",
            "incomplete": "incomplete",
            "incomplete_expired": "cancelled",
        }
        return mapping.get(stripe_status, "incomplete")

    async def _payment_from_invoice(self, invoice: dict[str, Any], *, status: str) -> Payment | None:
        stripe_sub_id = invoice.get("subscription")
        if not stripe_sub_id:
            return None
        subscription = await self._subscriptions.get_by_stripe_sub(str(stripe_sub_id))
        if subscription is None:
            log.warning("invoice webhook for unknown subscription=%s", stripe_sub_id)
            return None

        stripe_pi = str(invoice.get("payment_intent") or invoice.get("id"))
        existing = await self._payments.get_by_stripe_pi(stripe_pi)
        if existing is not None:
            return None

        now = self._now()
        amount_key = "amount_paid" if status == "succeeded" else "amount_due"
        return Payment(
            payment_id=str(ULID()),
            academy_id=subscription.academy_id,
            parent_id=subscription.parent_id,
            session_id=subscription.session_id,
            subscription_id=subscription.subscription_id,
            stripe_payment_intent_id=stripe_pi,
            amount_cents=int(invoice.get(amount_key) or invoice.get("amount_due") or 0),
            currency=str(invoice.get("currency") or "usd").lower(),
            status=status,  # type: ignore[arg-type]
            created_at=now,
            updated_at=now,
        )
