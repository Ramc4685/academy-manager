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
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.v2.contexts.billing.application.ports import (
    PaymentRepository,
    StripeEventDedup,
    StripeGateway,
    StudentBillingEnrollmentRepository,
    SubscriptionRepository,
)
from backend.v2.contexts.billing.domain.errors import InvalidWebhookSignature
from backend.v2.contexts.billing.domain.events import (
    CheckoutExpired,
    CheckoutExpiredPayload,
    InvoiceFailed,
    InvoiceLifecyclePayload,
    InvoicePaid,
    PaymentFailed,
    PaymentFailedPayload,
    PaymentRefunded,
    PaymentRefundedPayload,
    PaymentSucceeded,
    PaymentSucceededPayload,
    SubscriptionUpdated,
    SubscriptionUpdatedPayload,
)
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerInvoice,
    LedgerPayment,
)
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
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
        billing_enrollments: StudentBillingEnrollmentRepository | None = None,
        billing_ledger: Any | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._stripe = stripe
        self._dedup = dedup
        self._payments = payments
        self._subscriptions = subscriptions
        self._billing_enrollments = billing_enrollments
        self._billing_ledger = billing_ledger
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
        if await self._handle_session_type_invoice(invoice, paid=True):
            return
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
        if await self._handle_session_type_invoice(invoice, paid=False):
            return
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
                    reason=str(
                        invoice.get("last_finalization_error", {}).get(
                            "message", "invoice payment failed"
                        )
                    ),
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
        if event.get("type") == "customer.subscription.deleted":
            handled = await self._cancel_student_billing_enrollment(stripe_sub_id)
            if handled:
                return
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

    async def _cancel_student_billing_enrollment(self, stripe_sub_id: str) -> bool:
        if self._billing_enrollments is None:
            return False
        enrollment = await self._billing_enrollments.get_by_stripe_subscription(stripe_sub_id)
        if enrollment is None:
            return False
        if enrollment.status == "cancelled":
            return True
        await self._billing_enrollments.save(
            enrollment.model_copy(update={"status": "cancelled", "updated_at": self._now()})
        )
        return True

    async def _handle_session_type_invoice(self, invoice: dict[str, Any], *, paid: bool) -> bool:
        if self._billing_enrollments is None or self._billing_ledger is None:
            return False
        stripe_sub_id = self._stripe_subscription_id_from_invoice(invoice)
        if not stripe_sub_id:
            return False
        enrollment = await self._billing_enrollments.get_by_stripe_subscription(stripe_sub_id)
        if enrollment is None:
            return False

        now = self._now()
        invoice_id = self._ledger_invoice_id(invoice)
        amount_cents = int(
            invoice.get("amount_paid" if paid else "amount_due") or invoice.get("amount_due") or 0
        )
        period_label = self._invoice_period_label(invoice, now)
        ledger_invoice = await self._billing_ledger.create_invoice(
            LedgerInvoice(
                invoice_id=invoice_id,
                academy_id=enrollment.academy_id,
                parent_id=enrollment.parent_id,
                student_id=enrollment.student_id,
                enrollment_id=enrollment.enrollment_id,
                period=period_label,
                status="open",
                subtotal_cents=amount_cents,
                discount_cents=0,
                total_cents=amount_cents,
                balance_due_cents=amount_cents,
                currency=str(invoice.get("currency") or "usd").lower(),
                due_date=self._invoice_due_date(invoice, now),
                created_at=now,
                updated_at=now,
            ),
            lines=[
                InvoiceLine(
                    line_id=f"line-{invoice_id}",
                    academy_id=enrollment.academy_id,
                    invoice_id=invoice_id,
                    line_type="tuition",
                    description=f"Session type tuition {period_label}",
                    quantity=1,
                    unit_amount_cents=amount_cents,
                    amount_cents=amount_cents,
                    source_type="session_type",
                    source_id=enrollment.session_type_id,
                    created_at=now,
                )
            ],
            idempotency_key=f"stripe-invoice:{invoice.get('id')}",
        )
        event_cls = InvoicePaid if paid else InvoiceFailed
        if paid and amount_cents > 0:
            stripe_pi = str(invoice.get("payment_intent") or invoice.get("id"))
            payment = await self._billing_ledger.record_payment(
                LedgerPayment(
                    payment_id=f"ledger-pay-{invoice.get('id')}",
                    academy_id=enrollment.academy_id,
                    parent_id=enrollment.parent_id,
                    amount_cents=amount_cents,
                    unapplied_amount_cents=amount_cents,
                    currency=str(invoice.get("currency") or "usd").lower(),
                    status="succeeded",
                    payment_method="stripe",
                    stripe_payment_intent_id=stripe_pi,
                    paid_at=now,
                    created_at=now,
                    updated_at=now,
                ),
                idempotency_key=f"stripe-invoice-payment:{invoice.get('id')}",
            )
            allocation = await self._billing_ledger.allocate_payment(
                payment_id=payment.payment_id,
                invoice_id=ledger_invoice.invoice_id,
                amount_cents=amount_cents,
                idempotency_key=f"stripe-invoice-allocation:{invoice.get('id')}",
            )
            if allocation is not None:
                ledger_invoice = allocation.invoice
        await self._outbox.append(
            event_cls(
                aggregate_id=ledger_invoice.invoice_id,
                academy_id=ledger_invoice.academy_id,
                payload=self._invoice_payload(
                    ledger_invoice,
                    enrollment.student_id,
                    enrollment.session_type_id,
                    invoice,
                ),
            )
        )
        return True

    @staticmethod
    def _stripe_subscription_id_from_invoice(invoice: dict[str, Any]) -> str | None:
        direct = invoice.get("subscription")
        if direct:
            return str(direct)
        parent = invoice.get("parent")
        if isinstance(parent, dict):
            details = parent.get("subscription_details")
            if isinstance(details, dict) and details.get("subscription"):
                return str(details["subscription"])
        return None

    @staticmethod
    def _ledger_invoice_id(invoice: dict[str, Any]) -> str:
        metadata = invoice.get("metadata")
        if isinstance(metadata, dict) and metadata.get("ledger_invoice_id"):
            return str(metadata["ledger_invoice_id"])
        return f"ledger-{invoice.get('id')}"

    @staticmethod
    def _invoice_period_label(invoice: dict[str, Any], now: datetime) -> str:
        period_start = invoice.get("period_start")
        if period_start is not None:
            try:
                return datetime.fromtimestamp(int(period_start), tz=UTC).strftime("%Y-%m")
            except (TypeError, ValueError, OSError):
                pass
        return now.strftime("%Y-%m")

    @staticmethod
    def _invoice_due_date(invoice: dict[str, Any], now: datetime) -> date:
        due_timestamp = invoice.get("due_date")
        if due_timestamp is not None:
            try:
                return datetime.fromtimestamp(int(due_timestamp), tz=UTC).date()
            except (TypeError, ValueError, OSError):
                pass
        return (now + timedelta(days=30)).date()

    @staticmethod
    def _invoice_payload(
        invoice: LedgerInvoice,
        student_id: str | None,
        session_type_id: str | None,
        stripe_invoice: dict[str, Any],
    ) -> InvoiceLifecyclePayload:
        return InvoiceLifecyclePayload(
            invoice_id=invoice.invoice_id,
            parent_id=invoice.parent_id,
            student_id=student_id,
            session_type_id=session_type_id,
            billing_period_label=invoice.period,
            total_cents=invoice.total_cents,
            stripe_invoice_id=str(stripe_invoice.get("id")) if stripe_invoice.get("id") else None,
        )

    async def _payment_from_invoice(
        self, invoice: dict[str, Any], *, status: str
    ) -> Payment | None:
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
            payment_id=str(new_ulid()),
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
