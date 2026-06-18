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

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.v2.contexts.billing.application.ports import (
    EnrollmentAutopayStateRepository,
    EnrollmentBillingIdentity,
    EnrollmentBillingIdentityRepository,
    ParentStripeCustomerRepository,
    PaymentRepository,
    StripeEventDedup,
    StripeGateway,
    StripeInvoiceProcessingRepository,
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
from backend.v2.contexts.billing.domain.models import (
    Payment,
    can_transition_payment_projection,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import tenant_scope

log = logging.getLogger(__name__)

SUBSCRIPTION_INVOICE_RECOVERY_POINTS = {
    "received",
    "subscription_resolved",
    "ledger_invoice_synced",
    "ledger_payment_recorded",
    "ledger_allocated",
    "legacy_projection_saved",
    "processed",
    "quarantined",
}


class _QuarantineStripeEvent(Exception):
    """Stored event is valid Stripe input but unsafe to project into Mongo."""


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
        parent_customers: ParentStripeCustomerRepository | None = None,
        enrollment_autopay: EnrollmentAutopayStateRepository | None = None,
        enrollment_identity: EnrollmentBillingIdentityRepository | None = None,
        invoice_processing: StripeInvoiceProcessingRepository | None = None,
        expected_livemode: bool | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._stripe = stripe
        self._dedup = dedup
        self._payments = payments
        self._subscriptions = subscriptions
        self._billing_enrollments = billing_enrollments
        self._billing_ledger = billing_ledger
        self._parent_customers = parent_customers
        self._enrollment_autopay = enrollment_autopay
        self._enrollment_identity = enrollment_identity
        self._invoice_processing = invoice_processing
        self._expected_livemode = expected_livemode
        self._outbox = outbox
        self._academy_id = academy_id
        self._now = clock

    async def accept(self, payload: bytes, signature: str) -> dict[str, Any]:
        """Verify and persist a Stripe event, then return quickly.

        Business projection happens later via ``process_next`` so Stripe
        delivery is not blocked on Mongo ledger/customer/subscription writes.
        """
        event = self._verify(payload, signature)
        event_id, event_type = self._event_identity(event)

        with tenant_scope(self._academy_id):
            stored = await self._dedup.store_received(
                event,
                raw_payload=payload,
                academy_id=self._academy_id,
            )
        if not stored:
            log.info("stripe_webhook_already_stored event_id=%s", event_id)
        return {"received": True, "stored": stored, "type": event_type}

    async def process_next(
        self,
        *,
        processor_id: str,
        lock_seconds: int = 300,
    ) -> dict[str, Any]:
        with tenant_scope(self._academy_id):
            event_doc = await self._dedup.claim_next(
                academy_id=self._academy_id,
                processor_id=processor_id,
                lock_seconds=lock_seconds,
            )
            if event_doc is None:
                return {"processed": False, "empty": True}

            event_id = str(event_doc.get("event_id") or "")
            event_type = str(event_doc.get("event_type") or "")
            try:
                event = self._event_from_stored_payload(event_doc)
                event_type = event_type or str(event.get("type", ""))
                self._validate_livemode(event)
                event = await self._hydrate_current_stripe_object(event_type, event)
                self._validate_event_guards(event)
                await self._dispatch(event_type, event)
                await self._dedup.mark_processed(event_id)
                return {"processed": True, "event_id": event_id, "type": event_type}
            except _QuarantineStripeEvent as exc:
                await self._dedup.mark_quarantined(event_id, str(exc))
                return {
                    "processed": False,
                    "event_id": event_id,
                    "type": event_type,
                    "status": "quarantined",
                    "error": str(exc),
                }
            except Exception as exc:
                await self._dedup.mark_failed(event_id, str(exc))
                return {
                    "processed": False,
                    "event_id": event_id,
                    "type": event_type,
                    "status": "failed",
                    "error": str(exc),
                }

    async def execute(self, payload: bytes, signature: str) -> dict[str, Any]:
        event = self._verify(payload, signature)
        event_id, event_type = self._event_identity(event)

        with tenant_scope(self._academy_id):
            claimed = await self._dedup.claim(event_id, event_type)
            if not claimed:
                log.info("stripe_webhook_deduped event_id=%s", event_id)
                return {"received": True, "deduped": True}

            try:
                await self._dispatch(event_type, event)
                await self._dedup.mark_processed(event_id)
                return {"received": True, "type": event_type}
            except _QuarantineStripeEvent as exc:
                mark_quarantined = getattr(self._dedup, "mark_quarantined", None)
                if mark_quarantined is not None:
                    await mark_quarantined(event_id, str(exc))
                else:
                    await self._dedup.mark_failed(event_id, str(exc))
                return {
                    "received": True,
                    "type": event_type,
                    "status": "quarantined",
                    "error": str(exc),
                }
            except Exception as exc:
                await self._dedup.mark_failed(event_id, str(exc))
                raise

    def _verify(self, payload: bytes, signature: str) -> dict[str, Any]:
        try:
            event = self._stripe.verify_webhook(payload, signature)
        except Exception as exc:
            raise InvalidWebhookSignature(str(exc)) from exc
        if not isinstance(event, dict):
            raise InvalidWebhookSignature("event payload did not parse to object")
        self._event_identity(event)
        return event

    @staticmethod
    def _event_identity(event: dict[str, Any]) -> tuple[str, str]:
        event_id = str(event.get("id", ""))
        event_type = str(event.get("type", ""))
        if not event_id or not event_type:
            raise InvalidWebhookSignature("event missing id or type")
        return event_id, event_type

    @staticmethod
    def _event_from_stored_payload(event_doc: dict[str, Any]) -> dict[str, Any]:
        raw_payload = event_doc.get("raw_payload")
        if isinstance(raw_payload, bytes):
            decoded = raw_payload.decode("utf-8")
        elif isinstance(raw_payload, str):
            decoded = raw_payload
        elif isinstance(raw_payload, dict):
            return raw_payload
        else:
            raise ValueError("stored Stripe event missing raw payload")
        parsed = json.loads(decoded)
        if not isinstance(parsed, dict):
            raise ValueError("stored Stripe event raw payload is not an object")
        return parsed

    def _validate_event_guards(self, event: dict[str, Any]) -> None:
        self._validate_livemode(event)
        metadata = self._event_metadata(event)
        academy_id = metadata.get("academy_id")
        if academy_id and academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: event={academy_id} expected={self._academy_id}"
            )

    def _validate_livemode(self, event: dict[str, Any]) -> None:
        if self._expected_livemode is not None:
            livemode = bool(event.get("livemode", False))
            if livemode != self._expected_livemode:
                raise _QuarantineStripeEvent(
                    f"livemode mismatch: event={livemode} expected={self._expected_livemode}"
                )

    @staticmethod
    def _event_metadata(event: dict[str, Any]) -> dict[str, str]:
        obj = event.get("data", {}).get("object", {})
        if not isinstance(obj, dict):
            return {}
        metadata = obj.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        return {str(k): str(v) for k, v in metadata.items() if v is not None}

    async def _hydrate_current_stripe_object(
        self,
        event_type: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        obj = event.get("data", {}).get("object", {})
        if not isinstance(obj, dict):
            return event
        object_id = str(obj.get("id") or "")
        if not object_id:
            return event
        current: dict[str, Any] | None = None
        if event_type in ("checkout.session.completed", "checkout.session.expired"):
            current = await self._stripe.retrieve_checkout_session(object_id)
        elif event_type in ("invoice.paid", "invoice.payment_failed"):
            current = await self._stripe.retrieve_invoice(object_id)
        elif event_type in (
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            current = await self._stripe.retrieve_subscription(object_id)
        elif event_type in ("payment_intent.succeeded", "payment_intent.payment_failed"):
            current = await self._stripe.retrieve_payment_intent(object_id)
        if not current:
            return event
        merged = dict(obj)
        for key, value in current.items():
            if value not in (None, "", {}, []):
                merged[key] = value
        hydrated = dict(event)
        data = dict(hydrated.get("data") or {})
        data["object"] = merged
        hydrated["data"] = data
        return hydrated

    async def _dispatch(self, event_type: str, event: dict[str, Any]) -> None:
        if event_type == "checkout.session.completed":
            metadata = self._event_metadata(event)
            if metadata.get("source") == "invoice_pay_link" or metadata.get("invoice_id"):
                await self._handle_invoice_checkout_completed(event)
            else:
                await self._on_checkout_completed(event)
        elif event_type == "checkout.session.expired":
            await self._on_checkout_expired(event)
        elif event_type == "payment_intent.succeeded":
            metadata = self._event_metadata(event)
            if metadata.get("source") == "autopay" or metadata.get("invoice_id"):
                await self._handle_autopay_pi_succeeded(event)
            else:
                await self._on_payment_succeeded(event)
        elif event_type == "payment_intent.payment_failed":
            metadata = self._event_metadata(event)
            if metadata.get("source") == "autopay" or metadata.get("invoice_id"):
                await self._handle_autopay_pi_failed(event)
            elif await self._handle_invoice_checkout_payment_failed(event):
                return
            else:
                await self._on_payment_failed(event)
        elif event_type == "invoice.paid":
            await self._on_invoice_paid(event)
        elif event_type == "invoice.payment_failed":
            await self._on_invoice_payment_failed(event)
        elif event_type == "charge.refunded":
            await self._on_charge_refunded(event)
        elif event_type in (
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            await self._on_subscription_changed(event)
        else:
            log.info("stripe_webhook_ignored type=%s", event_type)

    async def _handle_invoice_checkout_completed(self, event: dict[str, Any]) -> None:
        """Handle checkout.session.completed from an invoice pay-link.

        Idempotent by checkout_session_id: if a ledger payment already exists
        for this session, the record_payment call returns the existing row and
        allocation is skipped via its own idempotency_key.
        """
        if self._billing_ledger is None:
            log.warning("invoice_checkout_completed: billing_ledger not configured — skipping")
            return

        obj = event["data"]["object"]
        checkout_session_id: str = str(obj.get("id") or "")
        metadata = obj.get("metadata") or {}
        invoice_id = str(metadata.get("invoice_id") or "")
        if not invoice_id:
            log.warning(
                "invoice_checkout_completed: no invoice_id in metadata session=%s",
                checkout_session_id,
            )
            return

        payment_intent_id: str | None = obj.get("payment_intent") or None
        if payment_intent_id:
            payment_intent_id = str(payment_intent_id)
        amount_total = int(obj.get("amount_total") or 0)
        currency = str(obj.get("currency") or "usd").lower()

        now = self._now()
        idempotency_key = f"invoice-checkout:{checkout_session_id}"
        ledger_payment_id = f"ledger-pay-cs:{checkout_session_id}"

        payment = await self._billing_ledger.record_payment(
            LedgerPayment(
                payment_id=ledger_payment_id,
                academy_id=self._academy_id,
                parent_id=str(metadata.get("parent_id") or "unknown"),
                amount_cents=amount_total,
                unapplied_amount_cents=amount_total,
                currency=currency,
                status="succeeded",
                payment_method="stripe_checkout",
                stripe_payment_intent_id=payment_intent_id,
                paid_at=now,
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=idempotency_key,
        )

        if amount_total > 0:
            await self._billing_ledger.allocate_payment(
                payment_id=payment.payment_id,
                invoice_id=invoice_id,
                amount_cents=amount_total,
                idempotency_key=f"invoice-checkout-alloc:{checkout_session_id}",
            )
            log.info(
                "invoice_checkout_completed: allocated payment=%s to invoice=%s amount=%d",
                payment.payment_id,
                invoice_id,
                amount_total,
            )

    async def _on_checkout_completed(self, event: dict[str, Any]) -> None:
        obj = event["data"]["object"]
        checkout_id = obj["id"]
        payment = await self._payments.get_by_checkout_session(checkout_id)
        subscription = await self._sync_subscription_from_checkout(obj)
        await self._persist_checkout_customer(obj, payment=payment, subscription=subscription)
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

    async def _persist_checkout_customer(
        self,
        checkout: dict[str, Any],
        *,
        payment: Payment | None,
        subscription: Any | None,
    ) -> None:
        if self._parent_customers is None:
            return
        stripe_customer_id = str(checkout.get("customer") or "")
        if not stripe_customer_id:
            return
        if payment is None and subscription is None:
            log.warning(
                "checkout.completed customer ignored without tenant-owned mapping checkout_id=%s",
                checkout.get("id"),
            )
            return
        parent_id = payment.parent_id if payment is not None else subscription.parent_id
        if not parent_id:
            log.warning(
                "checkout.completed customer present without parent_id checkout_id=%s",
                checkout.get("id"),
            )
            return
        await self._parent_customers.set_stripe_customer_id(
            parent_id=parent_id,
            stripe_customer_id=stripe_customer_id,
        )

    async def _sync_subscription_from_checkout(self, checkout: dict[str, Any]) -> Any | None:
        """Backfill the Stripe subscription id captured only after Checkout
        completes (it is null at session-creation time) and activate both the
        subscription row and the enrollment's autopay state. Without this,
        enrollments stay at subscription_status="incomplete" forever and
        subscription webhooks can't find the row by stripe_subscription_id.
        """
        stripe_sub_id = str(checkout.get("subscription") or "")
        if not stripe_sub_id:
            return None
        metadata = checkout.get("metadata")
        enrollment_id: str | None = None
        internal_sub_id: str | None = None
        if isinstance(metadata, dict):
            if metadata.get("enrollment_id"):
                enrollment_id = str(metadata["enrollment_id"])
            if metadata.get("app_subscription_id"):
                internal_sub_id = str(metadata["app_subscription_id"])
            if metadata.get("subscription_id"):
                internal_sub_id = internal_sub_id or str(metadata["subscription_id"])
        # Prefer the pending row this exact checkout created (its internal id
        # rides in the session metadata). A parent can start checkout several
        # times for one enrollment, so latest_for_enrollment may point at a
        # different pending row and is only a last-resort fallback.
        subscription = None
        if internal_sub_id:
            subscription = await self._subscriptions.get(internal_sub_id)
        if subscription is None:
            subscription = await self._subscriptions.get_by_stripe_sub(stripe_sub_id)
        if subscription is None:
            checkout_id = str(checkout.get("id") or "")
            if checkout_id:
                subscription = await self._subscriptions.get_by_checkout_session(checkout_id)
        if subscription is None and enrollment_id:
            subscription = await self._subscriptions.latest_for_enrollment(enrollment_id)
        if subscription is not None:
            updated = subscription.model_copy(
                update={
                    "stripe_subscription_id": stripe_sub_id,
                    "stripe_checkout_session_id": str(checkout.get("id") or "")
                    or subscription.stripe_checkout_session_id,
                    "status": "active",
                    "updated_at": self._now(),
                }
            )
            await self._subscriptions.save(updated)
            enrollment_id = enrollment_id or updated.enrollment_id
        else:
            log.warning(
                "checkout.completed subscription ignored without tenant-owned subscription checkout_id=%s",
                checkout.get("id"),
            )
            return None
        if self._enrollment_autopay is not None and enrollment_id:
            await self._enrollment_autopay.set_autopay_state(
                enrollment_id=enrollment_id,
                subscription_status="active",
                stripe_subscription_id=stripe_sub_id,
            )
        return updated

    @staticmethod
    def _checkout_parent_id(checkout: dict[str, Any]) -> str | None:
        metadata = checkout.get("metadata")
        if isinstance(metadata, dict):
            parent_id = metadata.get("parent_id")
            if parent_id:
                return str(parent_id)
        client_reference_id = checkout.get("client_reference_id")
        if client_reference_id:
            return str(client_reference_id)
        return None

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

    async def _handle_autopay_pi_succeeded(self, event: dict[str, Any]) -> None:
        """Handle payment_intent.succeeded from an autopay charge.

        Idempotent by pi_id via idempotency_key ``autopay-pi:{pi_id}``.
        Records a LedgerPayment and allocates it to the invoice.
        """
        if self._billing_ledger is None:
            log.warning("autopay_pi_succeeded: billing_ledger not configured — skipping")
            return

        pi = event["data"]["object"]
        pi_id: str = str(pi.get("id") or "")
        metadata = pi.get("metadata") or {}
        invoice_id = str(metadata.get("invoice_id") or "")

        if not invoice_id:
            log.warning("autopay_pi_succeeded: no invoice_id in metadata pi=%s", pi_id)
            return

        invoice = await self._billing_ledger.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError("autopay invoice not found")
        if invoice.academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: invoice={invoice.academy_id} expected={self._academy_id}"
            )

        amount_cents = int(pi.get("amount") or 0)
        if amount_cents <= 0:
            raise ValueError("autopay payment_intent missing positive amount")
        currency = str(pi.get("currency") or invoice.currency).lower()
        if currency != invoice.currency.lower():
            raise ValueError("autopay payment_intent currency does not match invoice")
        now = self._now()
        idempotency_key = f"autopay-pi:{pi_id}"
        ledger_payment_id = f"ledger-pay-autopay:{pi_id}"

        payment = await self._billing_ledger.record_payment(
            LedgerPayment(
                payment_id=ledger_payment_id,
                academy_id=invoice.academy_id,
                parent_id=invoice.parent_id,
                amount_cents=amount_cents,
                unapplied_amount_cents=amount_cents,
                currency=currency,
                status="succeeded",
                payment_method="stripe_autopay",
                stripe_payment_intent_id=pi_id,
                paid_at=now,
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=idempotency_key,
        )

        if amount_cents > 0:
            await self._billing_ledger.allocate_payment(
                payment_id=payment.payment_id,
                invoice_id=invoice_id,
                amount_cents=amount_cents,
                idempotency_key=f"autopay-alloc:{pi_id}",
            )
            log.info(
                "autopay_pi_succeeded: allocated payment=%s to invoice=%s pi=%s amount=%d",
                payment.payment_id,
                invoice_id,
                pi_id,
                amount_cents,
            )

    async def _handle_autopay_pi_failed(self, event: dict[str, Any]) -> None:
        """Handle payment_intent.payment_failed from an autopay charge.

        Per spec: log the decline, do NOT change invoice status.
        """
        pi = event["data"]["object"]
        pi_id: str = str(pi.get("id") or "")
        metadata = pi.get("metadata") or {}
        invoice_id = str(metadata.get("invoice_id") or "")
        last_error = pi.get("last_payment_error") or {}
        decline_code = str(last_error.get("decline_code") or last_error.get("code") or "unknown")
        log.warning(
            "autopay_pi_failed: pi=%s invoice=%s decline_code=%s — invoice status unchanged",
            pi_id,
            invoice_id,
            decline_code,
        )

    async def _handle_invoice_checkout_payment_failed(self, event: dict[str, Any]) -> bool:
        """Record a failed manual invoice Checkout attempt without closing the invoice."""
        if self._billing_ledger is None:
            return False

        event_id = str(event.get("id") or "")
        pi = event["data"]["object"]
        pi_id = str(pi.get("id") or "")
        checkout_session_id = _checkout_session_id_from_payment_intent(pi)
        if not checkout_session_id:
            return False

        checkout = await self._stripe.retrieve_checkout_session(checkout_session_id)
        metadata = checkout.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        invoice_id = str(metadata.get("invoice_id") or "")
        if metadata.get("source") != "invoice_pay_link" and not invoice_id:
            return False
        if not invoice_id:
            log.warning(
                "invoice_checkout_payment_failed: no invoice_id session=%s pi=%s",
                checkout_session_id,
                pi_id,
            )
            return True

        last_error = pi.get("last_payment_error") or {}
        if not isinstance(last_error, dict):
            last_error = {}
        failure_code = str(last_error.get("decline_code") or last_error.get("code") or "unknown")
        failure_message = str(last_error.get("message") or "Payment failed")
        amount_cents = int(pi.get("amount") or checkout.get("amount_total") or 0)
        currency = str(pi.get("currency") or checkout.get("currency") or "usd").lower()
        await self._billing_ledger.record_payment_attempt(
            invoice_id=invoice_id,
            parent_id=str(metadata.get("parent_id") or "unknown"),
            amount_cents=amount_cents,
            currency=currency,
            status="failed",
            stripe_payment_intent_id=pi_id or None,
            stripe_checkout_session_id=checkout_session_id,
            failure_code=failure_code,
            failure_message=failure_message,
            idempotency_key=f"invoice-checkout-failed:{invoice_id}:{pi_id or event_id}",
            created_by_event_id=event_id or None,
        )
        log.warning(
            "invoice_checkout_payment_failed: recorded attempt invoice=%s pi=%s code=%s",
            invoice_id,
            pi_id,
            failure_code,
        )
        return True

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

    async def _on_payment_succeeded(self, event: dict[str, Any]) -> None:
        pi = event["data"]["object"]
        pi_id = pi["id"]
        payment = await self._payments.get_by_stripe_pi(pi_id)
        if payment is None:
            return
        if payment.status == "succeeded":
            return
        updated = payment.model_copy(
            update={
                "status": "succeeded",
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

    async def _on_invoice_paid(self, event: dict[str, Any]) -> None:
        invoice = event["data"]["object"]
        if await self._handle_session_type_invoice(invoice, paid=True):
            return
        subscription = await self._subscription_from_invoice(invoice)
        if subscription is None:
            return
        event_id = str(event.get("id") or "")
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="subscription_resolved",
        )
        try:
            await self._sync_subscription_invoice_ledger(
                invoice,
                subscription=subscription,
                paid=True,
                event_id=event_id,
            )
        except _QuarantineStripeEvent as exc:
            await self._record_subscription_invoice_recovery_point(
                invoice,
                subscription=subscription,
                event_id=event_id,
                recovery_point="quarantined",
                last_error=str(exc),
            )
            raise
        payment = await self._payment_from_invoice(
            invoice,
            status="succeeded",
            subscription=subscription,
        )
        if payment is None:
            await self._record_subscription_invoice_recovery_point(
                invoice,
                subscription=subscription,
                event_id=event_id,
                recovery_point="processed",
            )
            return
        await self._payments.save(payment)
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="legacy_projection_saved",
            legacy_payment_id=payment.payment_id,
        )
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
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="processed",
            legacy_payment_id=payment.payment_id,
        )

    async def _on_invoice_payment_failed(self, event: dict[str, Any]) -> None:
        invoice = event["data"]["object"]
        if await self._handle_session_type_invoice(invoice, paid=False):
            return
        subscription = await self._subscription_from_invoice(invoice)
        if subscription is None:
            return
        event_id = str(event.get("id") or "")
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="subscription_resolved",
        )
        try:
            await self._sync_subscription_invoice_ledger(
                invoice,
                subscription=subscription,
                paid=False,
                event_id=event_id,
            )
        except _QuarantineStripeEvent as exc:
            await self._record_subscription_invoice_recovery_point(
                invoice,
                subscription=subscription,
                event_id=event_id,
                recovery_point="quarantined",
                last_error=str(exc),
            )
            raise
        payment = await self._payment_from_invoice(
            invoice, status="failed", subscription=subscription
        )
        if payment is None:
            await self._record_subscription_invoice_recovery_point(
                invoice,
                subscription=subscription,
                event_id=event_id,
                recovery_point="processed",
            )
            return
        await self._payments.save(payment)
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="legacy_projection_saved",
            legacy_payment_id=payment.payment_id,
        )
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
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="processed",
            legacy_payment_id=payment.payment_id,
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
        if self._enrollment_autopay is not None and updated.enrollment_id:
            await self._enrollment_autopay.set_autopay_state(
                enrollment_id=updated.enrollment_id,
                subscription_status=status,
                stripe_subscription_id=stripe_sub_id,
            )
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

    async def _sync_subscription_invoice_ledger(
        self,
        invoice: dict[str, Any],
        *,
        subscription: Any,
        paid: bool,
        event_id: str,
    ) -> LedgerInvoice | None:
        if self._billing_ledger is None:
            return None
        stripe_invoice_id = str(invoice.get("id") or "")
        if not stripe_invoice_id:
            raise _QuarantineStripeEvent("subscription invoice missing id")
        amount_cents = int(
            invoice.get("amount_paid" if paid else "amount_due") or invoice.get("amount_due") or 0
        )

        now = self._now()
        period_label = self._invoice_period_label(invoice, now)
        currency = str(invoice.get("currency") or "usd").lower()
        enrollment_id = subscription.enrollment_id
        identity = await self._subscription_enrollment_identity(subscription)
        student_id = _identity_value(identity, "student_id")
        parent_id = _identity_value(identity, "parent_id") or subscription.parent_id

        ledger_invoice = await self._billing_ledger.get_invoice_by_stripe_invoice_id(
            stripe_invoice_id
        )
        if enrollment_id:
            get_for_enrollment = getattr(
                self._billing_ledger,
                "get_invoice_for_enrollment_period",
                None,
            )
            if get_for_enrollment is not None:
                ledger_invoice = ledger_invoice or await get_for_enrollment(
                    enrollment_id,
                    period_label,
                    statuses={"draft", "open", "partially_paid", "paid"},
                )
            elif ledger_invoice is None:
                ledger_invoice = await self._billing_ledger.get_open_invoice_for_enrollment(
                    enrollment_id,
                    period_label,
                )
        if ledger_invoice is None and student_id:
            ledger_invoice = await self._billing_ledger.get_open_invoice_for_student(
                student_id,
                period_label,
            )

        if ledger_invoice is None:
            if amount_cents <= 0:
                return None
            invoice_id = self._ledger_invoice_id(invoice)
            ledger_invoice = await self._billing_ledger.create_invoice(
                LedgerInvoice(
                    invoice_id=invoice_id,
                    academy_id=subscription.academy_id,
                    parent_id=parent_id,
                    student_id=student_id,
                    enrollment_id=enrollment_id,
                    period=period_label,
                    status="open",
                    subtotal_cents=amount_cents,
                    discount_cents=0,
                    total_cents=amount_cents,
                    balance_due_cents=amount_cents,
                    currency=currency,
                    due_date=self._invoice_due_date(invoice, now),
                    stripe_invoice_id=stripe_invoice_id,
                    source_type="stripe_subscription",
                    source_id=stripe_invoice_id,
                    created_at=now,
                    updated_at=now,
                ),
                lines=[
                    InvoiceLine(
                        line_id=f"line-{invoice_id}",
                        academy_id=subscription.academy_id,
                        invoice_id=invoice_id,
                        line_type="tuition",
                        description=f"Subscription tuition {period_label}",
                        quantity=1,
                        unit_amount_cents=amount_cents,
                        amount_cents=amount_cents,
                        source_type="stripe_subscription",
                        source_id=stripe_invoice_id or subscription.stripe_subscription_id,
                        created_at=now,
                    )
                ],
                idempotency_key=f"stripe-subscription-invoice:{stripe_invoice_id}",
            )
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="ledger_invoice_synced",
            ledger_invoice_id=ledger_invoice.invoice_id,
        )

        if ledger_invoice.academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: invoice={ledger_invoice.academy_id} expected={self._academy_id}"
            )
        if ledger_invoice.parent_id != parent_id:
            raise _QuarantineStripeEvent(
                f"parent mismatch: invoice={ledger_invoice.parent_id} subscription={parent_id}"
            )
        if (
            ledger_invoice.stripe_invoice_id
            and ledger_invoice.stripe_invoice_id != stripe_invoice_id
        ):
            if paid and (ledger_invoice.status == "paid" or ledger_invoice.balance_due_cents <= 0):
                raise _QuarantineStripeEvent(
                    f"subscription invoice {stripe_invoice_id} matched already-paid invoice "
                    f"{ledger_invoice.invoice_id} already linked to "
                    f"{ledger_invoice.stripe_invoice_id}"
                )
            raise _QuarantineStripeEvent(
                f"subscription invoice {stripe_invoice_id} matched invoice "
                f"{ledger_invoice.invoice_id} already linked to {ledger_invoice.stripe_invoice_id}"
            )
        if paid and (ledger_invoice.status == "paid" or ledger_invoice.balance_due_cents <= 0):
            if ledger_invoice.stripe_invoice_id == stripe_invoice_id:
                return ledger_invoice
            raise _QuarantineStripeEvent(
                f"subscription invoice {stripe_invoice_id} matched already-paid invoice "
                f"{ledger_invoice.invoice_id}"
            )
        if ledger_invoice.stripe_invoice_id is None:
            ledger_invoice = await self._billing_ledger.save_invoice(
                ledger_invoice.model_copy(
                    update={
                        "stripe_invoice_id": stripe_invoice_id,
                        "source_type": ledger_invoice.source_type or "stripe_subscription",
                        "source_id": ledger_invoice.source_id or stripe_invoice_id,
                        "updated_at": now,
                    }
                )
            )
        if not paid:
            return ledger_invoice
        if amount_cents <= 0:
            return ledger_invoice

        stripe_payment_id = self._stripe_invoice_payment_identifier(invoice)
        payment = await self._billing_ledger.record_payment(
            LedgerPayment(
                payment_id=f"ledger-pay-{stripe_invoice_id}",
                academy_id=ledger_invoice.academy_id,
                parent_id=ledger_invoice.parent_id,
                amount_cents=amount_cents,
                unapplied_amount_cents=amount_cents,
                currency=currency,
                status="succeeded",
                payment_method="stripe_subscription",
                stripe_payment_intent_id=stripe_payment_id,
                stripe_invoice_id=stripe_invoice_id,
                paid_at=now,
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=f"stripe-invoice-payment:{stripe_invoice_id}",
        )
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="ledger_payment_recorded",
            ledger_invoice_id=ledger_invoice.invoice_id,
            ledger_payment_id=payment.payment_id,
        )
        await self._billing_ledger.allocate_payment(
            payment_id=payment.payment_id,
            invoice_id=ledger_invoice.invoice_id,
            amount_cents=amount_cents,
            idempotency_key=f"stripe-invoice-allocation:{stripe_invoice_id}",
        )
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="ledger_allocated",
            ledger_invoice_id=ledger_invoice.invoice_id,
            ledger_payment_id=payment.payment_id,
        )
        return await self._billing_ledger.get_invoice(ledger_invoice.invoice_id) or ledger_invoice

    async def _record_subscription_invoice_recovery_point(
        self,
        invoice: dict[str, Any],
        *,
        subscription: Any,
        event_id: str,
        recovery_point: str,
        ledger_invoice_id: str | None = None,
        ledger_payment_id: str | None = None,
        legacy_payment_id: str | None = None,
        last_error: str | None = None,
    ) -> None:
        if self._invoice_processing is None:
            return
        if recovery_point not in SUBSCRIPTION_INVOICE_RECOVERY_POINTS:
            raise ValueError(f"unknown subscription invoice recovery point: {recovery_point}")
        stripe_invoice_id = str(invoice.get("id") or "")
        if not stripe_invoice_id:
            return
        await self._invoice_processing.record_recovery_point(
            academy_id=subscription.academy_id,
            stripe_invoice_id=stripe_invoice_id,
            stripe_subscription_id=self._stripe_subscription_id_from_invoice(invoice)
            or subscription.stripe_subscription_id,
            event_id=event_id,
            recovery_point=recovery_point,
            ledger_invoice_id=ledger_invoice_id,
            ledger_payment_id=ledger_payment_id,
            legacy_payment_id=legacy_payment_id,
            last_error=last_error,
            updated_at=self._now(),
        )

    async def _subscription_enrollment_identity(
        self,
        subscription: Any,
    ) -> EnrollmentBillingIdentity | dict[str, str | None] | None:
        if self._enrollment_identity is None or not subscription.enrollment_id:
            return None
        identity = await self._enrollment_identity.get_billing_identity(subscription.enrollment_id)
        if identity is None:
            return None
        identity_academy = _identity_value(identity, "academy_id")
        if identity_academy and identity_academy != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: enrollment={identity_academy} expected={self._academy_id}"
            )
        identity_parent = _identity_value(identity, "parent_id")
        if identity_parent and identity_parent != subscription.parent_id:
            raise _QuarantineStripeEvent(
                f"parent mismatch: enrollment={identity_parent} subscription={subscription.parent_id}"
            )
        return identity

    async def _subscription_from_invoice(self, invoice: dict[str, Any]) -> Any | None:
        stripe_sub_id = self._stripe_subscription_id_from_invoice(invoice)
        if not stripe_sub_id:
            return None
        subscription = await self._subscriptions.get_by_stripe_sub(str(stripe_sub_id))
        if subscription is None:
            log.warning("invoice webhook for unknown subscription=%s", stripe_sub_id)
            return None
        if subscription.academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: subscription={subscription.academy_id} expected={self._academy_id}"
            )
        return subscription

    @staticmethod
    def _stripe_invoice_payment_identifier(invoice: dict[str, Any]) -> str:
        return str(invoice.get("payment_intent") or invoice.get("id"))

    async def _payment_from_invoice(
        self,
        invoice: dict[str, Any],
        *,
        status: str,
        subscription: Any | None = None,
    ) -> Payment | None:
        if subscription is None:
            subscription = await self._subscription_from_invoice(invoice)
        if subscription is None:
            return None

        stripe_pi = self._stripe_invoice_payment_identifier(invoice)
        existing = await self._payments.get_by_stripe_pi(stripe_pi)
        if existing is not None:
            if not can_transition_payment_projection(existing.status, status):
                raise _QuarantineStripeEvent(
                    f"invalid payment projection transition {existing.status}->{status}"
                )
            return None

        now = self._now()
        amount_key = "amount_paid" if status == "succeeded" else "amount_due"
        return Payment(
            payment_id=str(new_ulid()),
            academy_id=subscription.academy_id,
            parent_id=subscription.parent_id,
            enrollment_id=subscription.enrollment_id,
            session_id=subscription.session_id,
            subscription_id=subscription.subscription_id,
            stripe_payment_intent_id=stripe_pi,
            amount_cents=int(invoice.get(amount_key) or invoice.get("amount_due") or 0),
            currency=str(invoice.get("currency") or "usd").lower(),
            status=status,  # type: ignore[arg-type]
            created_at=now,
            updated_at=now,
        )


def _checkout_session_id_from_payment_intent(pi: dict[str, Any]) -> str | None:
    payment_details = pi.get("payment_details")
    if not isinstance(payment_details, dict):
        return None
    order_reference = str(payment_details.get("order_reference") or "")
    if order_reference.startswith("cs_"):
        return order_reference
    return None


def _identity_value(
    identity: EnrollmentBillingIdentity | dict[str, str | None] | None,
    key: str,
) -> str | None:
    if identity is None:
        return None
    if isinstance(identity, dict):
        value = identity.get(key)
    else:
        value = getattr(identity, key)
    return str(value) if value else None
