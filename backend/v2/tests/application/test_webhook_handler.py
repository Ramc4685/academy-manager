"""HandleWebhookEvent — Wave 2 fixture replay.

Asserts behavior for the canonical 10 Stripe scenarios (a representative
subset for unit-level coverage; full replay lives in the contract tests
which use real Stripe fixture JSON).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
    _QuarantineStripeEvent,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice, LedgerPayment
from backend.v2.contexts.billing.domain.models import Payment, Subscription
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)


class FakePaymentRepo:
    def __init__(self) -> None:
        self.by_id: dict[str, Payment] = {}
        self.by_checkout: dict[str, Payment] = {}
        self.by_pi: dict[str, Payment] = {}
        self.fail_next_save = False

    def seed(self, p: Payment) -> None:
        self.by_id[p.payment_id] = p
        if p.stripe_checkout_session_id:
            self.by_checkout[p.stripe_checkout_session_id] = p
        if p.stripe_payment_intent_id:
            self.by_pi[p.stripe_payment_intent_id] = p

    async def save(self, p: Payment) -> None:
        if self.fail_next_save:
            self.fail_next_save = False
            raise RuntimeError("transient payment write failed")
        self.seed(p)

    async def get(self, pid):
        return self.by_id.get(pid)

    async def get_by_stripe_pi(self, pi):
        return self.by_pi.get(pi)

    async def get_by_checkout_session(self, sid):
        return self.by_checkout.get(sid)

    async def list_for_parent(self, _):
        return list(self.by_id.values())


class FakeSubscriptionRepo:
    def __init__(self) -> None:
        self.by_id: dict[str, Subscription] = {}
        self.by_stripe_sub: dict[str, Subscription] = {}
        self.by_checkout: dict[str, Subscription] = {}
        self.by_enrollment: dict[str, Subscription] = {}

    def seed(self, subscription: Subscription) -> None:
        self.by_id[subscription.subscription_id] = subscription
        self.by_stripe_sub[subscription.stripe_subscription_id] = subscription
        if subscription.stripe_checkout_session_id:
            self.by_checkout[subscription.stripe_checkout_session_id] = subscription
        if subscription.enrollment_id:
            self.by_enrollment[subscription.enrollment_id] = subscription

    async def save(self, _):
        self.seed(_)

    async def get(self, subscription_id):
        return self.by_id.get(subscription_id)

    async def get_by_stripe_sub(self, stripe_sub):
        return self.by_stripe_sub.get(stripe_sub)

    async def get_by_checkout_session(self, checkout_session_id):
        return self.by_checkout.get(checkout_session_id)

    async def latest_for_enrollment(self, enrollment_id):
        return self.by_enrollment.get(enrollment_id)


class FakeDedup:
    def __init__(self) -> None:
        self.claimed: set[str] = set()
        self.processed: set[str] = set()
        self.events: dict[str, dict[str, Any]] = {}

    async def claim(self, event_id, _type):
        if event_id in self.claimed:
            return False
        self.claimed.add(event_id)
        return True

    async def mark_processed(self, event_id):
        self.processed.add(event_id)
        if event_id in self.events:
            self.events[event_id]["status"] = "processed"
            self.events[event_id]["processed_at"] = datetime.now(UTC)

    async def mark_failed(self, event_id, error):
        if event_id in self.events:
            self.events[event_id]["status"] = "failed"
            self.events[event_id]["error_message"] = error

    async def mark_quarantined(self, event_id, error):
        if event_id in self.events:
            self.events[event_id]["status"] = "quarantined"
            self.events[event_id]["error_message"] = error

    async def store_received(self, event, *, raw_payload, academy_id):
        event_id = str(event["id"])
        if event_id in self.events:
            return False
        self.events[event_id] = {
            "event_id": event_id,
            "event_type": str(event["type"]),
            "academy_id": academy_id,
            "livemode": bool(event.get("livemode", False)),
            "status": "received",
            "retry_count": 0,
            "raw_payload": raw_payload,
            "received_at": datetime.now(UTC),
        }
        return True

    async def claim_next(self, *, academy_id, processor_id, lock_seconds=300):
        now = datetime.now(UTC)
        for event in self.events.values():
            if event.get("academy_id") != academy_id:
                continue
            retry_at = event.get("next_retry_at")
            if isinstance(retry_at, datetime) and retry_at > now:
                continue
            if event["status"] in {"received", "failed"}:
                event["status"] = "processing"
                event["processor_id"] = processor_id
                event["processing_started_at"] = now
                event["processing_locked_until"] = now + timedelta(seconds=lock_seconds)
                return dict(event)
        return None


class FakeInvoiceProcessing:
    def __init__(self) -> None:
        self.by_key: dict[str, dict[str, Any]] = {}

    async def record_recovery_point(
        self,
        *,
        academy_id: str,
        stripe_invoice_id: str,
        stripe_subscription_id: str | None,
        event_id: str,
        recovery_point: str,
        ledger_invoice_id: str | None = None,
        ledger_payment_id: str | None = None,
        legacy_payment_id: str | None = None,
        last_error: str | None = None,
        updated_at: datetime,
    ) -> None:
        key = f"{academy_id}:stripe_invoice:{stripe_invoice_id}"
        row = self.by_key.setdefault(
            key,
            {
                "academy_id": academy_id,
                "business_key": f"stripe_invoice:{stripe_invoice_id}",
                "stripe_invoice_id": stripe_invoice_id,
                "event_ids": [],
            },
        )
        if event_id not in row["event_ids"]:
            row["event_ids"].append(event_id)
        row.update(
            {
                "stripe_subscription_id": stripe_subscription_id,
                "recovery_point": recovery_point,
                "last_error": last_error,
                "updated_at": updated_at,
            }
        )
        if ledger_invoice_id is not None:
            row["ledger_invoice_id"] = ledger_invoice_id
        if ledger_payment_id is not None:
            row["ledger_payment_id"] = ledger_payment_id
        if legacy_payment_id is not None:
            row["legacy_payment_id"] = legacy_payment_id


class FakeOutbox:
    def __init__(self) -> None:
        self.events: list[Any] = []
        self.event_ids: set[str] = set()

    async def append(self, event, *, session=None):
        if event.event_id in self.event_ids:
            raise DuplicateKeyError("duplicate event_id")
        self.event_ids.add(event.event_id)
        self.events.append(event)

    async def pull_unprocessed(self, limit=100):
        return []

    async def mark_processed(self, _):
        pass


class FakeParentStripeCustomers:
    def __init__(self) -> None:
        self.saved: list[dict[str, str]] = []
        self.default_methods: list[dict[str, Any]] = []

    async def set_stripe_customer_id(self, *, parent_id: str, stripe_customer_id: str) -> None:
        self.saved.append({"parent_id": parent_id, "stripe_customer_id": stripe_customer_id})

    async def set_default_payment_method(
        self,
        *,
        parent_id: str,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        setup_intent_id: str,
        checkout_session_id: str | None,
        completed_at: datetime,
        current_consent_id: str | None = None,
        consent_text_version: str | None = None,
        ach_mandate_version: str | None = None,
        card_disclosure_version: str | None = None,
        setup_status: str = "active",
        payment_method_role: str = "primary",
        payment_method_label: str | None = None,
        payment_method_last4: str | None = None,
        session=None,
    ) -> None:
        row = {
            "parent_id": parent_id,
            "stripe_customer_id": stripe_customer_id,
            "stripe_payment_method_id": stripe_payment_method_id,
            "payment_method_type": payment_method_type,
            "stripe_mandate_id": stripe_mandate_id,
            "setup_intent_id": setup_intent_id,
            "checkout_session_id": checkout_session_id,
            "completed_at": completed_at,
            "setup_status": setup_status,
            "payment_method_role": payment_method_role,
        }
        if payment_method_label:
            row["payment_method_label"] = payment_method_label
        if payment_method_last4:
            row["payment_method_last4"] = payment_method_last4
        if current_consent_id:
            row["current_consent_id"] = current_consent_id
        if consent_text_version:
            row["consent_text_version"] = consent_text_version
        if ach_mandate_version:
            row["ach_mandate_version"] = ach_mandate_version
        if card_disclosure_version:
            row["card_disclosure_version"] = card_disclosure_version
        self.default_methods = [
            existing
            for existing in self.default_methods
            if not (
                existing["parent_id"] == parent_id
                and existing.get("payment_method_role", "primary") == payment_method_role
            )
        ]
        self.default_methods.append(row)

    async def promote_payment_method_to_default(
        self,
        *,
        parent_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        payment_method_label: str | None = None,
        payment_method_last4: str | None = None,
    ) -> None:
        for row in reversed(self.default_methods):
            if row["parent_id"] != parent_id:
                continue
            row["default_payment_method_id"] = stripe_payment_method_id
            row["default_payment_method_type"] = payment_method_type
            if payment_method_label:
                row["default_payment_method_label"] = payment_method_label
            if payment_method_last4:
                row["default_payment_method_last4"] = payment_method_last4
            if stripe_mandate_id:
                row["default_stripe_mandate_id"] = stripe_mandate_id
            return
        self.default_methods.append(
            {
                "parent_id": parent_id,
                "default_payment_method_id": stripe_payment_method_id,
                "default_payment_method_type": payment_method_type,
                "default_stripe_mandate_id": stripe_mandate_id,
            }
        )
        if payment_method_label:
            self.default_methods[-1]["default_payment_method_label"] = payment_method_label
        if payment_method_last4:
            self.default_methods[-1]["default_payment_method_last4"] = payment_method_last4


class FakeEnrollmentAutopayState:
    def __init__(self) -> None:
        self.synced: list[dict[str, str | None]] = []
        self.setup_completed: list[str] = []

    async def set_autopay_state(
        self,
        *,
        enrollment_id: str,
        autopay_enrollment_status: str,
        session=None,
    ) -> bool:
        self.synced.append(
            {
                "enrollment_id": enrollment_id,
                "autopay_enrollment_status": autopay_enrollment_status,
            }
        )
        return True

    async def mark_autopay_active_from_setup(self, *, enrollment_id: str, session=None) -> bool:
        if enrollment_id not in self.setup_completed:
            self.setup_completed.append(enrollment_id)
        return True


class FakeAutopayConsentRepo:
    def __init__(self) -> None:
        self.consents: list[Any] = []
        self.by_setup_intent: dict[str, Any] = {}

    async def append(self, consent, *, session=None):
        existing = self.by_setup_intent.get(consent.setup_intent_id)
        if existing is not None:
            return existing
        self.consents.append(consent)
        self.by_setup_intent[consent.setup_intent_id] = consent
        return consent


class FakeEnrollmentBillingIdentity:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, str | None]] = {}

    def seed(
        self,
        *,
        academy_id: str = "acad",
        enrollment_id: str,
        parent_id: str,
        student_id: str | None,
        session_id: str | None,
    ) -> None:
        self.rows[enrollment_id] = {
            "academy_id": academy_id,
            "parent_id": parent_id,
            "student_id": student_id,
            "enrollment_id": enrollment_id,
            "session_id": session_id,
        }

    async def get_billing_identity(self, enrollment_id: str) -> dict[str, str | None] | None:
        return self.rows.get(enrollment_id)


class FakeBillingLedger:
    def __init__(self, invoice: LedgerInvoice | None = None) -> None:
        self.invoices = {invoice.invoice_id: invoice} if invoice else {}
        self.invoice_keys: dict[str, str] = {}
        self.lines: dict[str, list[Any]] = {}
        self.payments: dict[str, LedgerPayment] = {}
        self.payment_keys: dict[str, str] = {}
        self.allocations: list[dict[str, Any]] = []
        self.allocation_keys: set[str] = set()
        self.payment_attempts: dict[str, dict[str, Any]] = {}
        self.fail_allocate = False

    async def create_invoice(
        self,
        invoice: LedgerInvoice,
        *,
        lines: list[Any],
        idempotency_key: str,
    ) -> LedgerInvoice:
        existing_id = self.invoice_keys.get(idempotency_key)
        if existing_id is not None:
            return self.invoices[existing_id]
        existing = self.invoices.get(invoice.invoice_id)
        if existing is not None:
            self.invoice_keys[idempotency_key] = existing.invoice_id
            return existing
        self.invoices[invoice.invoice_id] = invoice
        self.lines[invoice.invoice_id] = lines
        self.invoice_keys[idempotency_key] = invoice.invoice_id
        return invoice

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self.invoices.get(invoice_id)

    async def get_invoice_by_stripe_invoice_id(
        self, stripe_invoice_id: str
    ) -> LedgerInvoice | None:
        for invoice in self.invoices.values():
            if invoice.stripe_invoice_id == stripe_invoice_id:
                return invoice
        return None

    async def get_lines_for_invoice(self, invoice_id: str) -> list[Any]:
        return list(self.lines.get(invoice_id, []))

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        self.invoices[invoice.invoice_id] = invoice
        return invoice

    async def get_open_invoice_for_enrollment(
        self, enrollment_id: str, period: str
    ) -> LedgerInvoice | None:
        for invoice in self.invoices.values():
            if (
                invoice.enrollment_id == enrollment_id
                and invoice.period == period
                and invoice.status in {"open", "draft", "partially_paid"}
            ):
                return invoice
        return None

    async def get_invoice_for_enrollment_period(
        self,
        enrollment_id: str,
        period: str,
        *,
        statuses: set[str] | None = None,
    ) -> LedgerInvoice | None:
        for invoice in self.invoices.values():
            if invoice.enrollment_id != enrollment_id or invoice.period != period:
                continue
            if statuses is not None and invoice.status not in statuses:
                continue
            return invoice
        return None

    async def get_open_invoice_for_student(
        self, student_id: str, period: str
    ) -> LedgerInvoice | None:
        for invoice in self.invoices.values():
            if (
                invoice.student_id == student_id
                and invoice.period == period
                and invoice.status in {"open", "draft", "partially_paid"}
            ):
                return invoice
        return None

    async def record_payment(
        self,
        payment: LedgerPayment,
        *,
        idempotency_key: str,
    ) -> LedgerPayment:
        existing_id = self.payment_keys.get(idempotency_key)
        if existing_id is not None:
            return self.payments[existing_id]
        self.payments[payment.payment_id] = payment
        self.payment_keys[idempotency_key] = payment.payment_id
        return payment

    async def get_payment_allocation_by_idempotency_key(
        self, idempotency_key: str
    ) -> dict[str, Any] | None:
        for allocation in self.allocations:
            if allocation["idempotency_key"] == idempotency_key:
                return allocation
        return None

    async def record_payment_attempt(
        self,
        *,
        invoice_id: str,
        parent_id: str,
        amount_cents: int,
        currency: str,
        status: str,
        stripe_payment_intent_id: str | None,
        stripe_checkout_session_id: str | None,
        failure_code: str | None,
        failure_message: str | None,
        idempotency_key: str,
        created_by_event_id: str | None = None,
    ) -> dict[str, Any]:
        existing = self.payment_attempts.get(idempotency_key)
        if existing is not None:
            return existing
        attempt = {
            "invoice_id": invoice_id,
            "parent_id": parent_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "status": status,
            "stripe_payment_intent_id": stripe_payment_intent_id,
            "stripe_checkout_session_id": stripe_checkout_session_id,
            "failure_code": failure_code,
            "failure_message": failure_message,
            "idempotency_key": idempotency_key,
            "created_by_event_id": created_by_event_id,
        }
        self.payment_attempts[idempotency_key] = attempt
        return attempt

    async def allocate_payment(
        self,
        *,
        payment_id: str,
        invoice_id: str,
        amount_cents: int,
        idempotency_key: str,
    ) -> None:
        if self.fail_allocate:
            raise ValueError("allocation failed")
        if idempotency_key in self.allocation_keys:
            return None
        invoice = self.invoices[invoice_id]
        payment = self.payments[payment_id]
        allocated = min(amount_cents, invoice.balance_due_cents)
        self.invoices[invoice_id] = invoice.model_copy(
            update={
                "balance_due_cents": max(invoice.balance_due_cents - allocated, 0),
                "status": "paid"
                if invoice.balance_due_cents - allocated <= 0
                else "partially_paid",
            }
        )
        self.payments[payment_id] = payment.model_copy(
            update={
                "unapplied_amount_cents": max(payment.unapplied_amount_cents - allocated, 0),
            }
        )
        self.allocation_keys.add(idempotency_key)
        self.allocations.append(
            {
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "amount_cents": amount_cents,
                "idempotency_key": idempotency_key,
            }
        )

    async def get_payment_by_stripe_payment_intent_id(
        self, stripe_payment_intent_id: str
    ) -> LedgerPayment | None:
        for payment in self.payments.values():
            if payment.stripe_payment_intent_id == stripe_payment_intent_id:
                return payment
        return None

    async def mark_payment_refunded(
        self,
        payment_id: str,
        *,
        refunded_cents: int,
        status: str,
        updated_at: Any,
    ) -> LedgerPayment:
        payment = self.payments[payment_id]
        updated = payment.model_copy(
            update={
                "refunded_cents": refunded_cents,
                "status": status,
                "updated_at": updated_at,
            }
        )
        self.payments[payment_id] = updated
        return updated

    async def reverse_payment_allocation(
        self,
        *,
        allocation_idempotency_key: str,
        reversal_idempotency_key: str,
        reason: str,
        return_code: str | None,
        reversed_at: datetime,
    ) -> dict[str, Any] | None:
        for allocation in list(self.allocations):
            if allocation["idempotency_key"] != allocation_idempotency_key:
                continue
            invoice = self.invoices[allocation["invoice_id"]]
            payment = self.payments[allocation["payment_id"]]
            self.allocations.remove(allocation)
            self.allocation_keys.discard(allocation_idempotency_key)
            self.invoices[invoice.invoice_id] = invoice.model_copy(
                update={
                    "status": "open",
                    "balance_due_cents": invoice.total_cents,
                    "updated_at": reversed_at,
                }
            )
            self.payments[payment.payment_id] = payment.model_copy(
                update={"unapplied_amount_cents": 0, "updated_at": reversed_at}
            )
            return {
                "payment_id": payment.payment_id,
                "invoice_id": invoice.invoice_id,
                "amount_cents": allocation["amount_cents"],
                "reason": reason,
                "return_code": return_code,
                "idempotency_key": reversal_idempotency_key,
            }
        return None


def _build(
    repo,
    outbox=None,
    dedup=None,
    subscriptions=None,
    parent_customers=None,
    enrollment_autopay=None,
    enrollment_identity=None,
    stripe=None,
    expected_livemode=None,
    billing_ledger=None,
    invoice_processing=None,
    billing_enrollments=None,
    consent_repo=None,
):
    return HandleWebhookEvent(
        stripe=stripe or FakeStripeGateway(),
        dedup=dedup or FakeDedup(),
        payments=repo,
        subscriptions=subscriptions or FakeSubscriptionRepo(),
        billing_enrollments=billing_enrollments,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consent_repo,
        enrollment_identity=enrollment_identity,
        outbox=outbox or FakeOutbox(),
        academy_id="acad",
        expected_livemode=expected_livemode,
        billing_ledger=billing_ledger,
        invoice_processing=invoice_processing,
    )


class _FakeBillingEnrollmentsForGuard:
    """Minimal billing-enrollment lookup for the legacy-convergence guard.

    ``get(enrollment_id)`` returns an object exposing ``stripe_subscription_id``
    so ``_enrollment_is_legacy_subscription_managed`` can decide whether a
    subscription event still governs the enrollment (HIGH review-fix #4).
    """

    def __init__(self, *, enrollment_id: str, stripe_subscription_id: str | None) -> None:
        self._enrollment_id = enrollment_id
        self._stripe_subscription_id = stripe_subscription_id

    async def get(self, enrollment_id: str):
        if enrollment_id != self._enrollment_id:
            return None
        return SimpleNamespace(
            enrollment_id=self._enrollment_id,
            stripe_subscription_id=self._stripe_subscription_id,
        )

    async def get_by_stripe_subscription(self, stripe_subscription_id: str):
        return None


def _ledger_invoice(
    *,
    invoice_id: str = "inv-autopay",
    academy_id: str = "acad",
    parent_id: str = "parent-from-invoice",
    student_id: str | None = None,
    enrollment_id: str | None = None,
    period: str = "2026-06",
    balance_due_cents: int = 10_000,
    status: str = "open",
) -> LedgerInvoice:
    now = datetime.now(UTC)
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=academy_id,
        parent_id=parent_id,
        student_id=student_id,
        enrollment_id=enrollment_id,
        period=period,
        status=status,  # type: ignore[arg-type]
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=now.date(),
        created_at=now,
        updated_at=now,
    )


def _seed_pending_payment(repo: FakePaymentRepo) -> Payment:
    now = datetime.now(UTC)
    p = Payment(
        payment_id="pay-1",
        academy_id="acad",
        parent_id="p1",
        session_id="s1",
        stripe_checkout_session_id="cs_1",
        amount_cents=15000,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    repo.seed(p)
    return p


@pytest.mark.asyncio
async def test_accept_stores_webhook_event_without_business_side_effects() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    outbox = FakeOutbox()
    dedup = FakeDedup()
    uc = _build(repo, outbox=outbox, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_async_accept",
            "type": "checkout.session.completed",
            "livemode": True,
            "data": {
                "object": {
                    "id": "cs_1",
                    "payment_intent": "pi_1",
                    "metadata": {"academy_id": "acad"},
                }
            },
        }
    ).encode()

    res = await uc.accept(body, "test_signature")

    assert res == {"received": True, "stored": True, "type": "checkout.session.completed"}
    assert dedup.events["evt_async_accept"]["status"] == "received"
    assert repo.by_id["pay-1"].status == "pending"
    assert outbox.events == []


@pytest.mark.asyncio
async def test_process_next_projects_stored_event_and_marks_processed() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    outbox = FakeOutbox()
    dedup = FakeDedup()
    uc = _build(repo, outbox=outbox, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_async_process",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "payment_intent": "pi_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res == {
        "processed": True,
        "event_id": "evt_async_process",
        "type": "checkout.session.completed",
    }
    assert repo.by_id["pay-1"].status == "succeeded"
    assert repo.by_id["pay-1"].stripe_payment_intent_id == "pi_1"
    assert dedup.events["evt_async_process"]["status"] == "processed"
    assert [e.name for e in outbox.events] == ["Billing.PaymentSucceeded"]


@pytest.mark.asyncio
async def test_process_next_fetches_current_checkout_before_projection() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    subscriptions = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subscriptions.seed(
        Subscription(
            subscription_id="app-sub-1",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="pending:cs_1",
            status="incomplete",
            created_at=now,
            updated_at=now,
        )
    )
    stripe = FakeStripeGateway()
    stripe.subscription_checkouts.append(
        {
            "checkout_id": "cs_1",
            "stripe_subscription_id": "sub_live_1",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "session_id": "s1",
            "amount_cents": 15000,
            "metadata": {
                "academy_id": "acad",
                "parent_id": "p1",
                "enrollment_id": "enr-1",
                "app_subscription_id": "app-sub-1",
            },
        }
    )
    parent_customers = FakeParentStripeCustomers()
    enrollment_autopay = FakeEnrollmentAutopayState()
    dedup = FakeDedup()
    uc = _build(
        repo,
        dedup=dedup,
        subscriptions=subscriptions,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        stripe=stripe,
    )
    body = json.dumps(
        {
            "id": "evt_hydrate_checkout",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert repo.by_id["pay-1"].status == "succeeded"
    assert parent_customers.saved == [{"parent_id": "p1", "stripe_customer_id": "cus_fake_parent"}]
    assert subscriptions.by_id["app-sub-1"].stripe_subscription_id == "sub_live_1"
    assert subscriptions.by_id["app-sub-1"].status == "active"
    assert enrollment_autopay.setup_completed == ["enr-1"]
    assert enrollment_autopay.synced == []


@pytest.mark.asyncio
async def test_autopay_setup_checkout_and_setup_intent_replay_do_not_duplicate_consent_event() -> (
    None
):
    repo = FakePaymentRepo()
    subscriptions = FakeSubscriptionRepo()
    stripe = FakeStripeGateway()
    stripe.autopay_setup_checkouts.append(
        {
            "checkout_id": "cs_setup_replay",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "session_id": "s1",
            "setup_intent_id": "seti_replay",
            "metadata": {
                "academy_id": "acad",
                "parent_id": "p1",
                "enrollment_id": "enr-1",
                "source": "autopay_setup",
            },
        }
    )
    stripe.setup_intents["seti_replay"] = {
        "id": "seti_replay",
        "object": "setup_intent",
        "customer": "cus_parent",
        "payment_method": "pm_replay",
        "mandate": None,
        "metadata": {
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
        },
    }
    stripe.payment_methods["pm_replay"] = {
        "id": "pm_replay",
        "object": "payment_method",
        "type": "card",
    }
    parent_customers = FakeParentStripeCustomers()
    enrollment_autopay = FakeEnrollmentAutopayState()
    consents = FakeAutopayConsentRepo()
    outbox = FakeOutbox()
    uc = _build(
        repo,
        outbox=outbox,
        subscriptions=subscriptions,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        stripe=stripe,
    )

    checkout_body = json.dumps(
        {
            "id": "evt_autopay_setup_checkout_replay",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_setup_replay"}},
        }
    ).encode()
    setup_intent_body = json.dumps(
        {
            "id": "evt_setup_intent_succeeded_replay",
            "type": "setup_intent.succeeded",
            "data": {"object": {"id": "seti_replay"}},
        }
    ).encode()

    await uc.accept(checkout_body, "test_signature")
    await uc.process_next(processor_id="test-worker")
    await uc.accept(setup_intent_body, "test_signature")
    await uc.process_next(processor_id="test-worker")

    assert [consent.setup_intent_id for consent in consents.consents] == ["seti_replay"]
    assert [event.name for event in outbox.events] == ["Billing.AutopayConsentCaptured"]
    assert [row["setup_intent_id"] for row in parent_customers.default_methods] == ["seti_replay"]
    assert enrollment_autopay.setup_completed == ["enr-1"]


@pytest.mark.asyncio
async def test_autopay_setup_checkout_completed_sets_default_pm_without_subscription_row() -> None:
    repo = FakePaymentRepo()
    subscriptions = FakeSubscriptionRepo()
    stripe = FakeStripeGateway()
    stripe.autopay_setup_checkouts.append(
        {
            "checkout_id": "cs_setup_1",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "session_id": "s1",
            "setup_intent_id": "seti_setup_1",
            "metadata": {
                "academy_id": "acad",
                "parent_id": "p1",
                "enrollment_id": "enr-1",
                "source": "autopay_setup",
            },
        }
    )
    stripe.setup_intents["seti_setup_1"] = {
        "id": "seti_setup_1",
        "object": "setup_intent",
        "customer": "cus_parent",
        "payment_method": "pm_bank",
        "mandate": "mandate_bank",
        "metadata": {
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
        },
    }
    stripe.payment_methods["pm_bank"] = {
        "id": "pm_bank",
        "object": "payment_method",
        "type": "us_bank_account",
    }
    parent_customers = FakeParentStripeCustomers()
    enrollment_autopay = FakeEnrollmentAutopayState()
    dedup = FakeDedup()
    uc = _build(
        repo,
        dedup=dedup,
        subscriptions=subscriptions,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        stripe=stripe,
    )
    body = json.dumps(
        {
            "id": "evt_autopay_setup_checkout",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_setup_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert subscriptions.by_id == {}
    assert stripe.customer_default_payment_methods == [
        {
            "stripe_customer_id": "cus_parent",
            "stripe_payment_method_id": "pm_bank",
            "metadata": {"academy_id": "acad", "parent_id": "p1"},
        }
    ]
    assert parent_customers.default_methods[0] | {"completed_at": None} == {
        "parent_id": "p1",
        "stripe_customer_id": "cus_parent",
        "stripe_payment_method_id": "pm_bank",
        "payment_method_type": "us_bank_account",
        "stripe_mandate_id": "mandate_bank",
        "setup_intent_id": "seti_setup_1",
        "checkout_session_id": "cs_setup_1",
        "completed_at": None,
        "setup_status": "active",
        "payment_method_role": "primary",
        "default_payment_method_id": "pm_bank",
        "default_payment_method_type": "us_bank_account",
        "default_stripe_mandate_id": "mandate_bank",
    }
    assert enrollment_autopay.setup_completed == ["enr-1"]
    assert enrollment_autopay.synced == []


@pytest.mark.asyncio
async def test_setup_intent_succeeded_completes_autopay_from_setup_metadata() -> None:
    repo = FakePaymentRepo()
    subscriptions = FakeSubscriptionRepo()
    stripe = FakeStripeGateway()
    stripe.setup_intents["seti_replay"] = {
        "id": "seti_replay",
        "object": "setup_intent",
        "customer": "cus_parent",
        "payment_method": "pm_card",
        "mandate": None,
        "metadata": {
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
        },
    }
    stripe.payment_methods["pm_card"] = {
        "id": "pm_card",
        "object": "payment_method",
        "type": "card",
    }
    parent_customers = FakeParentStripeCustomers()
    enrollment_autopay = FakeEnrollmentAutopayState()
    dedup = FakeDedup()
    uc = _build(
        repo,
        dedup=dedup,
        subscriptions=subscriptions,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        stripe=stripe,
    )
    body = json.dumps(
        {
            "id": "evt_setup_intent_succeeded",
            "type": "setup_intent.succeeded",
            "data": {"object": {"id": "seti_replay"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    first = await uc.process_next(processor_id="test-worker")
    second = await uc.process_next(processor_id="test-worker")

    assert first["processed"] is True
    assert second == {"processed": False, "empty": True}
    assert subscriptions.by_id == {}
    assert stripe.customer_default_payment_methods == [
        {
            "stripe_customer_id": "cus_parent",
            "stripe_payment_method_id": "pm_card",
            "metadata": {"academy_id": "acad", "parent_id": "p1"},
        }
    ]
    assert parent_customers.default_methods[0]["checkout_session_id"] is None
    assert parent_customers.default_methods[0]["payment_method_type"] == "card"
    assert parent_customers.default_methods[0]["setup_status"] == "active"
    assert parent_customers.default_methods[0]["payment_method_role"] == "primary"
    assert enrollment_autopay.setup_completed == ["enr-1"]
    assert enrollment_autopay.synced == []


@pytest.mark.asyncio
async def test_ach_setup_requiring_microdeposit_verification_does_not_mark_active() -> None:
    repo = FakePaymentRepo()
    subscriptions = FakeSubscriptionRepo()
    stripe = FakeStripeGateway()
    stripe.autopay_setup_checkouts.append(
        {
            "checkout_id": "cs_setup_verify",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "session_id": "s1",
            "setup_intent_id": "seti_setup_verify",
            "metadata": {
                "academy_id": "acad",
                "parent_id": "p1",
                "enrollment_id": "enr-1",
                "source": "autopay_setup",
            },
        }
    )
    stripe.setup_intents["seti_setup_verify"] = {
        "id": "seti_setup_verify",
        "object": "setup_intent",
        "status": "requires_action",
        "next_action": {"type": "verify_with_microdeposits"},
        "customer": "cus_parent",
        "payment_method": "pm_bank_pending",
        "mandate": "mandate_bank_pending",
        "metadata": {
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
        },
    }
    stripe.payment_methods["pm_bank_pending"] = {
        "id": "pm_bank_pending",
        "object": "payment_method",
        "type": "us_bank_account",
    }
    parent_customers = FakeParentStripeCustomers()
    enrollment_autopay = FakeEnrollmentAutopayState()
    dedup = FakeDedup()
    uc = _build(
        repo,
        dedup=dedup,
        subscriptions=subscriptions,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        stripe=stripe,
    )
    body = json.dumps(
        {
            "id": "evt_autopay_setup_verify",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_setup_verify"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert stripe.customer_default_payment_methods == []
    assert parent_customers.default_methods[0]["setup_status"] == "verification_required"
    assert parent_customers.default_methods[0]["payment_method_type"] == "us_bank_account"
    assert parent_customers.default_methods[0]["payment_method_role"] == "primary"
    assert enrollment_autopay.setup_completed == []
    assert enrollment_autopay.synced == []


@pytest.mark.asyncio
async def test_active_fallback_card_setup_does_not_mark_enrollment_active_or_default() -> None:
    repo = FakePaymentRepo()
    stripe = FakeStripeGateway()
    stripe.setup_intents["seti_card_fallback"] = {
        "id": "seti_card_fallback",
        "object": "setup_intent",
        "status": "succeeded",
        "customer": "cus_parent",
        "payment_method": "pm_card_fallback",
        "mandate": None,
        "metadata": {
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
            "payment_method_role": "fallback",
        },
    }
    stripe.payment_methods["pm_card_fallback"] = {
        "id": "pm_card_fallback",
        "object": "payment_method",
        "type": "card",
    }
    parent_customers = FakeParentStripeCustomers()
    enrollment_autopay = FakeEnrollmentAutopayState()
    dedup = FakeDedup()
    uc = _build(
        repo,
        dedup=dedup,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        stripe=stripe,
    )
    body = json.dumps(
        {
            "id": "evt_setup_intent_card_fallback",
            "type": "setup_intent.succeeded",
            "data": {"object": {"id": "seti_card_fallback"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert stripe.customer_default_payment_methods == []
    assert parent_customers.default_methods[0]["setup_status"] == "active"
    assert parent_customers.default_methods[0]["payment_method_role"] == "fallback"
    assert parent_customers.default_methods[0]["payment_method_type"] == "card"
    assert enrollment_autopay.setup_completed == []


@pytest.mark.asyncio
async def test_checkout_completed_without_tenant_owned_mapping_does_not_mutate_customer_or_autopay() -> (
    None
):
    repo = FakePaymentRepo()
    parent_customers = FakeParentStripeCustomers()
    enrollment_autopay = FakeEnrollmentAutopayState()
    outbox = FakeOutbox()
    uc = _build(
        repo,
        outbox=outbox,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
    )
    body = json.dumps(
        {
            "id": "evt_unknown_checkout",
            "type": "checkout.session.completed",
            "livemode": True,
            "data": {
                "object": {
                    "id": "cs_unknown",
                    "customer": "cus_wrong_tenant",
                    "subscription": "sub_wrong_tenant",
                    "payment_intent": "pi_wrong_tenant",
                    "metadata": {
                        "academy_id": "acad",
                        "parent_id": "parent-from-metadata",
                        "enrollment_id": "enrollment-from-metadata",
                    },
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    result = await uc.process_next(processor_id="worker-1")

    assert result["processed"] is True
    assert parent_customers.saved == []
    assert enrollment_autopay.synced == []
    assert enrollment_autopay.setup_completed == []
    assert repo.by_id == {}
    assert outbox.events == []


@pytest.mark.asyncio
async def test_failed_stored_event_can_be_retried_later() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    repo.fail_next_save = True
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_async_retry",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "payment_intent": "pi_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    failed = await uc.process_next(processor_id="test-worker")
    retried = await uc.process_next(processor_id="test-worker")

    assert failed["processed"] is False
    assert failed["status"] == "failed"
    assert dedup.events["evt_async_retry"]["status"] == "processed"
    assert retried["processed"] is True
    assert repo.by_id["pay-1"].status == "succeeded"


@pytest.mark.asyncio
async def test_wrong_livemode_event_is_quarantined() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup, expected_livemode=True)
    body = json.dumps(
        {
            "id": "evt_wrong_mode",
            "type": "checkout.session.completed",
            "livemode": False,
            "data": {"object": {"id": "cs_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["status"] == "quarantined"
    assert dedup.events["evt_wrong_mode"]["status"] == "quarantined"
    assert repo.by_id["pay-1"].status == "pending"


@pytest.mark.asyncio
async def test_tenant_mismatch_event_is_quarantined() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    dedup = FakeDedup()

    class MismatchedStripeGateway(FakeStripeGateway):
        async def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, Any]:
            return {
                "id": checkout_session_id,
                "object": "checkout.session",
                "status": "complete",
                "payment_status": "paid",
                "metadata": {"academy_id": "other-academy"},
            }

    uc = _build(repo, dedup=dedup, stripe=MismatchedStripeGateway())
    body = json.dumps(
        {
            "id": "evt_wrong_tenant",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_1",
                    "metadata": {"academy_id": "acad"},
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["status"] == "quarantined"
    assert dedup.events["evt_wrong_tenant"]["status"] == "quarantined"
    assert repo.by_id["pay-1"].status == "pending"


@pytest.mark.asyncio
async def test_process_next_quarantines_mismatched_metadata_events() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_other_academy_pending",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_1",
                    "metadata": {"academy_id": "other-academy"},
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["status"] == "quarantined"
    assert dedup.events["evt_other_academy_pending"]["status"] == "quarantined"
    assert repo.by_id["pay-1"].status == "pending"


@pytest.mark.asyncio
async def test_payment_intent_succeeded_marks_payment_succeeded() -> None:
    repo = FakePaymentRepo()
    payment = _seed_pending_payment(repo)
    repo.seed(payment.model_copy(update={"stripe_payment_intent_id": "pi_1"}))
    outbox = FakeOutbox()
    dedup = FakeDedup()
    uc = _build(repo, outbox=outbox, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_pi_succeeded",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert repo.by_id["pay-1"].status == "succeeded"
    assert [e.name for e in outbox.events] == ["Billing.PaymentSucceeded"]


@pytest.mark.asyncio
async def test_autopay_payment_intent_uses_invoice_parent_when_metadata_parent_missing() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice())
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger)
    body = json.dumps(
        {
            "id": "evt_autopay_pi_succeeded",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_autopay_1",
                    "amount": 10000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-autopay",
                        "source": "autopay",
                    },
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    payment = ledger.payments["ledger-pay-autopay:pi_autopay_1"]
    assert payment.parent_id == "parent-from-invoice"
    assert payment.academy_id == "acad"
    assert ledger.allocations == [
        {
            "payment_id": "ledger-pay-autopay:pi_autopay_1",
            "invoice_id": "inv-autopay",
            "amount_cents": 10000,
            "idempotency_key": "autopay-alloc:pi_autopay_1",
        }
    ]


@pytest.mark.asyncio
async def test_autopay_payment_intent_succeeded_records_discount_metadata_when_webhook_wins() -> (
    None
):
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(
        _ledger_invoice(
            balance_due_cents=9_750,
        )
    )
    ledger.lines["inv-autopay"] = [
        InvoiceLine(
            line_id="ach-discount:inv-autopay",
            academy_id="acad",
            invoice_id="inv-autopay",
            line_type="ach_discount",
            description="ACH autopay savings",
            quantity=1,
            unit_amount_cents=-250,
            amount_cents=-250,
            source_type="autopay_cash_discount",
            source_id="cash-discount-v1",
            created_at=datetime.now(UTC),
        )
    ]
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger)
    body = json.dumps(
        {
            "id": "evt_autopay_pi_metadata",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_autopay_metadata",
                    "amount": 9750,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-autopay",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                        "ach_discount_cents": "250",
                        "ach_discount_line_id": "ach-discount:inv-autopay",
                        "ach_discount_percent": "2.5",
                        "disclosure_version": "cash-discount-v1",
                        "funding_type": "us_bank_account",
                    },
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    payment = ledger.payments["ledger-pay-autopay:pi_autopay_metadata"]
    assert payment.metadata == {
        "ach_discount_cents": "250",
        "ach_discount_line_id": "ach-discount:inv-autopay",
        "ach_discount_percent": "2.5",
        "disclosure_version": "cash-discount-v1",
        "funding_type": "us_bank_account",
        "invoice_id": "inv-autopay",
    }


@pytest.mark.asyncio
async def test_autopay_ach_payment_intent_processing_records_pending_attempt_only() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-autopay-processing"))
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger)
    body = json.dumps(
        {
            "id": "evt_autopay_pi_processing",
            "type": "payment_intent.processing",
            "data": {
                "object": {
                    "id": "pi_autopay_processing",
                    "amount": 10000,
                    "currency": "usd",
                    "payment_method_types": ["us_bank_account"],
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-autopay-processing",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                        "funding_type": "us_bank_account",
                    },
                    "status": "processing",
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert ledger.invoices["inv-autopay-processing"].status == "open"
    assert ledger.invoices["inv-autopay-processing"].balance_due_cents == 10000
    assert ledger.payments == {}
    assert ledger.allocations == []
    assert list(ledger.payment_attempts.values()) == [
        {
            "invoice_id": "inv-autopay-processing",
            "parent_id": "parent-from-invoice",
            "amount_cents": 10000,
            "currency": "usd",
            "status": "processing",
            "stripe_payment_intent_id": "pi_autopay_processing",
            "stripe_checkout_session_id": None,
            "failure_code": None,
            "failure_message": "ACH debit submitted; awaiting settlement.",
            "idempotency_key": "autopay-processing:inv-autopay-processing:pi_autopay_processing",
            "created_by_event_id": "evt_autopay_pi_processing",
        }
    ]


@pytest.mark.asyncio
async def test_autopay_ach_processing_cross_tenant_invoice_is_quarantined() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-other", academy_id="other-acad"))
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger)
    body = json.dumps(
        {
            "id": "evt_autopay_pi_processing_tenant",
            "type": "payment_intent.processing",
            "data": {
                "object": {
                    "id": "pi_autopay_processing_tenant",
                    "amount": 10000,
                    "currency": "usd",
                    "payment_method_types": ["us_bank_account"],
                    "metadata": {
                        "academy_id": "other-acad",
                        "invoice_id": "inv-other",
                        "source": "autopay",
                    },
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["status"] == "quarantined"
    assert ledger.payments == {}
    assert ledger.allocations == []
    assert ledger.payment_attempts == {}


@pytest.mark.asyncio
async def test_autopay_payment_intent_parent_metadata_mismatch_is_quarantined() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(parent_id="parent-from-invoice"))
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger)
    body = json.dumps(
        {
            "id": "evt_autopay_pi_parent_mismatch",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_autopay_parent_mismatch",
                    "amount": 10000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-autopay",
                        "parent_id": "parent-from-metadata",
                        "source": "autopay",
                    },
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["status"] == "quarantined"
    assert dedup.events["evt_autopay_pi_parent_mismatch"]["status"] == "quarantined"
    assert ledger.payments == {}
    assert ledger.allocations == []


@pytest.mark.asyncio
async def test_autopay_payment_intent_allocation_failure_is_retryable() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice())
    ledger.fail_allocate = True
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger)
    body = json.dumps(
        {
            "id": "evt_autopay_pi_retry",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_autopay_retry",
                    "amount": 10000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-autopay",
                        "source": "autopay",
                    },
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    failed = await uc.process_next(processor_id="test-worker")

    assert failed["status"] == "failed"
    assert dedup.events["evt_autopay_pi_retry"]["status"] == "failed"
    assert "evt_autopay_pi_retry" not in dedup.processed


@pytest.mark.asyncio
async def test_autopay_payment_intent_failed_records_attempt_without_closing_invoice() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-autopay-failed", status="open"))
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger)
    body = json.dumps(
        {
            "id": "evt_autopay_pi_failed",
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": "pi_autopay_failed",
                    "amount": 10000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-autopay-failed",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                    },
                    "last_payment_error": {
                        "code": "card_declined",
                        "decline_code": "insufficient_funds",
                        "message": "Your card has insufficient funds.",
                    },
                    "status": "requires_payment_method",
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert ledger.invoices["inv-autopay-failed"].status == "open"
    assert ledger.invoices["inv-autopay-failed"].balance_due_cents == 10000
    assert ledger.allocations == []
    assert ledger.payments == {}
    assert list(ledger.payment_attempts.values()) == [
        {
            "invoice_id": "inv-autopay-failed",
            "parent_id": "parent-from-invoice",
            "amount_cents": 10000,
            "currency": "usd",
            "status": "failed",
            "stripe_payment_intent_id": "pi_autopay_failed",
            "stripe_checkout_session_id": None,
            "failure_code": "insufficient_funds",
            "failure_message": "Your card has insufficient funds.",
            "idempotency_key": "autopay-failed:inv-autopay-failed:pi_autopay_failed",
            "created_by_event_id": "evt_autopay_pi_failed",
        }
    ]


@pytest.mark.asyncio
async def test_autopay_ach_return_after_paid_reopens_invoice_and_records_return_code() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-ach-return"))
    dedup = FakeDedup()
    outbox = FakeOutbox()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger, outbox=outbox)
    succeeded = json.dumps(
        {
            "id": "evt_ach_return_succeeded",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_ach_return",
                    "amount": 10000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-ach-return",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                        "funding_type": "us_bank_account",
                        "funding_type_source": "server_payment_method",
                    },
                }
            },
        }
    ).encode()
    returned = json.dumps(
        {
            "id": "evt_ach_return_refund",
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_ach_return",
                    "payment_intent": "pi_ach_return",
                    "amount_refunded": 10000,
                    "failure_code": "insufficient_funds",
                    "payment_method_details": {"type": "us_bank_account"},
                }
            },
        }
    ).encode()

    await uc.accept(succeeded, "test_signature")
    assert (await uc.process_next(processor_id="test-worker"))["processed"] is True
    assert ledger.invoices["inv-ach-return"].status == "paid"
    await uc.accept(returned, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    invoice = ledger.invoices["inv-ach-return"]
    payment = ledger.payments["ledger-pay-autopay:pi_ach_return"]
    assert payment.metadata["funding_type"] == "us_bank_account"
    assert payment.metadata["funding_type_source"] == "server_payment_method"
    assert invoice.status == "open"
    assert invoice.balance_due_cents == 10000
    assert payment.status == "refunded"
    assert payment.refunded_cents == 10000
    assert payment.unapplied_amount_cents == 0
    assert ledger.allocations == []
    returned_attempts = [
        attempt for attempt in ledger.payment_attempts.values() if attempt["status"] == "returned"
    ]
    assert returned_attempts == [
        {
            "invoice_id": "inv-ach-return",
            "parent_id": "parent-from-invoice",
            "amount_cents": 10000,
            "currency": "usd",
            "status": "returned",
            "stripe_payment_intent_id": "pi_ach_return",
            "stripe_checkout_session_id": None,
            "failure_code": "R01",
            "failure_message": "ACH return R01",
            "idempotency_key": "autopay-ach-return:inv-ach-return:pi_ach_return:R01:10000",
            "created_by_event_id": "evt_ach_return_refund",
        }
    ]
    events_after_return = len(outbox.events)
    duplicate_return = json.loads(returned.decode())
    duplicate_return["id"] = "evt_ach_return_refund_duplicate"
    await uc.accept(json.dumps(duplicate_return).encode(), "test_signature")
    duplicate_res = await uc.process_next(processor_id="test-worker")
    assert duplicate_res["processed"] is True
    assert ledger.invoices["inv-ach-return"].status == "open"
    assert ledger.allocations == []
    assert len(outbox.events) == events_after_return
    alternate_return = json.dumps(
        {
            "id": "evt_ach_return_payment_failed_duplicate",
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": "pi_ach_return",
                    "amount": 10000,
                    "currency": "usd",
                    "payment_method_types": ["us_bank_account"],
                    "last_payment_error": {"code": "insufficient_funds"},
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-ach-return",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                    },
                }
            },
        }
    ).encode()
    await uc.accept(alternate_return, "test_signature")
    alternate_res = await uc.process_next(processor_id="test-worker")
    assert alternate_res["processed"] is True
    assert ledger.invoices["inv-ach-return"].status == "open"
    assert ledger.allocations == []
    assert len(outbox.events) == events_after_return


@pytest.mark.asyncio
async def test_autopay_ach_return_replay_emits_missing_refund_event_after_ledger_mutation() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-ach-return-replay"))
    dedup = FakeDedup()
    outbox = FakeOutbox()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger, outbox=outbox)
    succeeded = json.dumps(
        {
            "id": "evt_ach_return_replay_succeeded",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_ach_return_replay",
                    "amount": 10000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-ach-return-replay",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                        "funding_type": "us_bank_account",
                        "funding_type_source": "server_payment_method",
                    },
                }
            },
        }
    ).encode()
    returned_without_details = json.dumps(
        {
            "id": "evt_ach_return_replay_refund",
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_ach_return_replay",
                    "payment_intent": "pi_ach_return_replay",
                    "amount_refunded": 10000,
                    "failure_code": "insufficient_funds",
                }
            },
        }
    ).encode()

    await uc.accept(succeeded, "test_signature")
    assert (await uc.process_next(processor_id="test-worker"))["processed"] is True
    await ledger.mark_payment_refunded(
        "ledger-pay-autopay:pi_ach_return_replay",
        refunded_cents=10000,
        status="refunded",
        updated_at=datetime.now(UTC),
    )
    await ledger.reverse_payment_allocation(
        allocation_idempotency_key="autopay-alloc:pi_ach_return_replay",
        reversal_idempotency_key="ach-return:pi_ach_return_replay:10000:R01",
        reason="ach_return",
        return_code="R01",
        reversed_at=datetime.now(UTC),
    )

    await uc.accept(returned_without_details, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    refund_events = [event for event in outbox.events if event.name == "Billing.PaymentRefunded"]
    assert len(refund_events) == 1
    assert refund_events[0].event_id == (
        "billing-payment-refunded:ach-return:pi_ach_return_replay:10000:R01"
    )
    assert refund_events[0].payload.reason == "other"


@pytest.mark.asyncio
async def test_partial_ach_return_is_recorded_as_unsupported_without_reversing_allocation() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-ach-partial-return"))
    dedup = FakeDedup()
    outbox = FakeOutbox()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger, outbox=outbox)
    succeeded = json.dumps(
        {
            "id": "evt_ach_partial_return_succeeded",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_ach_partial_return",
                    "amount": 10000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-ach-partial-return",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                    },
                    "payment_method_types": ["us_bank_account"],
                }
            },
        }
    ).encode()
    partial_return = json.dumps(
        {
            "id": "evt_ach_partial_return_refund",
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_ach_partial_return",
                    "payment_intent": "pi_ach_partial_return",
                    "amount_refunded": 4000,
                    "failure_code": "insufficient_funds",
                    "payment_method_details": {"type": "us_bank_account"},
                }
            },
        }
    ).encode()

    await uc.accept(succeeded, "test_signature")
    assert (await uc.process_next(processor_id="test-worker"))["processed"] is True
    await uc.accept(partial_return, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    invoice = ledger.invoices["inv-ach-partial-return"]
    payment = ledger.payments["ledger-pay-autopay:pi_ach_partial_return"]
    assert invoice.status == "paid"
    assert invoice.balance_due_cents == 0
    assert payment.status == "succeeded"
    assert payment.refunded_cents == 0
    assert ledger.allocations == [
        {
            "payment_id": "ledger-pay-autopay:pi_ach_partial_return",
            "invoice_id": "inv-ach-partial-return",
            "amount_cents": 10000,
            "idempotency_key": "autopay-alloc:pi_ach_partial_return",
        }
    ]
    attempts = list(ledger.payment_attempts.values())
    assert attempts == [
        {
            "invoice_id": "inv-ach-partial-return",
            "parent_id": "parent-from-invoice",
            "amount_cents": 4000,
            "currency": "usd",
            "status": "failed",
            "stripe_payment_intent_id": "pi_ach_partial_return",
            "stripe_checkout_session_id": None,
            "failure_code": "unsupported_partial_ach_return",
            "failure_message": "Unsupported partial ACH return R01 for 4000 of 10000 cents",
            "idempotency_key": (
                "autopay-ach-return-unsupported-partial:"
                "inv-ach-partial-return:pi_ach_partial_return:R01:4000"
            ),
            "created_by_event_id": "evt_ach_partial_return_refund",
        }
    ]
    assert not any(type(event).__name__ == "PaymentRefunded" for event in outbox.events)


@pytest.mark.asyncio
async def test_metadata_only_funding_type_with_return_code_on_refund_does_not_reopen_invoice() -> (
    None
):
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-metadata-bank-false-positive"))
    dedup = FakeDedup()
    outbox = FakeOutbox()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger, outbox=outbox)
    succeeded = json.dumps(
        {
            "id": "evt_metadata_bank_false_positive_succeeded",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_metadata_bank_false_positive",
                    "amount": 10000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-metadata-bank-false-positive",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                        "funding_type": "us_bank_account",
                    },
                }
            },
        }
    ).encode()
    returned = json.dumps(
        {
            "id": "evt_metadata_bank_false_positive_refund",
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_metadata_bank_false_positive",
                    "payment_intent": "pi_metadata_bank_false_positive",
                    "amount_refunded": 10000,
                    "failure_code": "insufficient_funds",
                }
            },
        }
    ).encode()

    await uc.accept(succeeded, "test_signature")
    assert (await uc.process_next(processor_id="test-worker"))["processed"] is True
    await uc.accept(returned, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    invoice = ledger.invoices["inv-metadata-bank-false-positive"]
    payment = ledger.payments["ledger-pay-autopay:pi_metadata_bank_false_positive"]
    assert invoice.status == "paid"
    assert invoice.balance_due_cents == 0
    assert payment.status == "refunded"
    assert payment.refunded_cents == 10000
    assert ledger.allocations == [
        {
            "payment_id": "ledger-pay-autopay:pi_metadata_bank_false_positive",
            "invoice_id": "inv-metadata-bank-false-positive",
            "amount_cents": 10000,
            "idempotency_key": "autopay-alloc:pi_metadata_bank_false_positive",
        }
    ]
    assert not any(attempt["status"] == "returned" for attempt in ledger.payment_attempts.values())
    assert outbox.events[-1].payload.reason == "admin_initiated"


@pytest.mark.asyncio
async def test_metadata_only_funding_type_with_payment_failed_return_code_does_not_reopen_invoice() -> (
    None
):
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-metadata-pi-false-positive"))
    dedup = FakeDedup()
    outbox = FakeOutbox()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger, outbox=outbox)
    succeeded = json.dumps(
        {
            "id": "evt_metadata_pi_false_positive_succeeded",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_metadata_pi_false_positive",
                    "amount": 10000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-metadata-pi-false-positive",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                        "funding_type": "us_bank_account",
                    },
                }
            },
        }
    ).encode()
    failed = json.dumps(
        {
            "id": "evt_metadata_pi_false_positive_failed",
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": "pi_metadata_pi_false_positive",
                    "amount": 10000,
                    "currency": "usd",
                    "last_payment_error": {"code": "insufficient_funds"},
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-metadata-pi-false-positive",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                        "funding_type": "us_bank_account",
                    },
                }
            },
        }
    ).encode()

    await uc.accept(succeeded, "test_signature")
    assert (await uc.process_next(processor_id="test-worker"))["processed"] is True
    await uc.accept(failed, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    invoice = ledger.invoices["inv-metadata-pi-false-positive"]
    payment = ledger.payments["ledger-pay-autopay:pi_metadata_pi_false_positive"]
    assert invoice.status == "paid"
    assert invoice.balance_due_cents == 0
    assert payment.status == "succeeded"
    assert payment.refunded_cents == 0
    assert len(ledger.allocations) == 1
    attempts = list(ledger.payment_attempts.values())
    assert attempts == [
        {
            "invoice_id": "inv-metadata-pi-false-positive",
            "parent_id": "parent-from-invoice",
            "amount_cents": 10000,
            "currency": "usd",
            "status": "failed",
            "stripe_payment_intent_id": "pi_metadata_pi_false_positive",
            "stripe_checkout_session_id": None,
            "failure_code": "insufficient_funds",
            "failure_message": "Payment failed",
            "idempotency_key": (
                "autopay-failed:" "inv-metadata-pi-false-positive:pi_metadata_pi_false_positive"
            ),
            "created_by_event_id": "evt_metadata_pi_false_positive_failed",
        }
    ]


@pytest.mark.asyncio
async def test_metadata_only_ach_return_code_on_refund_does_not_reopen_invoice() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-ach-normal-refund"))
    dedup = FakeDedup()
    outbox = FakeOutbox()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger, outbox=outbox)
    succeeded = json.dumps(
        {
            "id": "evt_ach_normal_refund_succeeded",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_ach_normal_refund",
                    "amount": 10000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-ach-normal-refund",
                        "parent_id": "parent-from-invoice",
                        "source": "autopay",
                        "funding_type": "us_bank_account",
                    },
                }
            },
        }
    ).encode()
    metadata_only_refund = json.dumps(
        {
            "id": "evt_ach_normal_refund",
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_ach_normal_refund",
                    "payment_intent": "pi_ach_normal_refund",
                    "amount_refunded": 10000,
                    "metadata": {"ach_return_code": "R01"},
                }
            },
        }
    ).encode()

    await uc.accept(succeeded, "test_signature")
    assert (await uc.process_next(processor_id="test-worker"))["processed"] is True
    await uc.accept(metadata_only_refund, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    invoice = ledger.invoices["inv-ach-normal-refund"]
    payment = ledger.payments["ledger-pay-autopay:pi_ach_normal_refund"]
    assert invoice.status == "paid"
    assert invoice.balance_due_cents == 0
    assert payment.status == "refunded"
    assert payment.refunded_cents == 10000
    assert ledger.allocations == [
        {
            "payment_id": "ledger-pay-autopay:pi_ach_normal_refund",
            "invoice_id": "inv-ach-normal-refund",
            "amount_cents": 10000,
            "idempotency_key": "autopay-alloc:pi_ach_normal_refund",
        }
    ]
    assert not any(attempt["status"] == "returned" for attempt in ledger.payment_attempts.values())
    assert outbox.events[-1].payload.reason == "admin_initiated"


@pytest.mark.asyncio
async def test_invoice_checkout_payment_intent_failed_records_attempt_without_closing_invoice() -> (
    None
):
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-checkout-failed", status="open"))
    stripe = FakeStripeGateway()
    stripe.checkouts.append(
        {
            "checkout_id": "cs_invoice_failed",
            "parent_id": "parent-from-invoice",
            "session_id": "invoice-pay-link",
            "amount_cents": 1236,
            "metadata": {
                "source": "invoice_pay_link",
                "invoice_id": "inv-checkout-failed",
                "parent_id": "parent-from-invoice",
            },
        }
    )
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup, billing_ledger=ledger, stripe=stripe)
    body = json.dumps(
        {
            "id": "evt_invoice_checkout_failed",
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": "pi_invoice_checkout_failed",
                    "amount": 1236,
                    "currency": "usd",
                    "metadata": {},
                    "payment_details": {"order_reference": "cs_invoice_failed"},
                    "last_payment_error": {
                        "code": "card_declined",
                        "decline_code": "insufficient_funds",
                        "message": "Your card has insufficient funds.",
                    },
                    "status": "requires_payment_method",
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert ledger.invoices["inv-checkout-failed"].status == "open"
    assert ledger.invoices["inv-checkout-failed"].balance_due_cents == 10000
    assert ledger.allocations == []
    assert ledger.payments == {}
    assert list(ledger.payment_attempts.values()) == [
        {
            "invoice_id": "inv-checkout-failed",
            "parent_id": "parent-from-invoice",
            "amount_cents": 1236,
            "currency": "usd",
            "status": "failed",
            "stripe_payment_intent_id": "pi_invoice_checkout_failed",
            "stripe_checkout_session_id": "cs_invoice_failed",
            "failure_code": "insufficient_funds",
            "failure_message": "Your card has insufficient funds.",
            "idempotency_key": (
                "invoice-checkout-failed:inv-checkout-failed:pi_invoice_checkout_failed"
            ),
            "created_by_event_id": "evt_invoice_checkout_failed",
        }
    ]


@pytest.mark.asyncio
async def test_invoice_checkout_payment_intent_succeeded_does_not_allocate_before_session() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-checkout-pi",
            parent_id="parent-checkout",
            balance_due_cents=6_000,
        )
    )
    uc = _build(repo, billing_ledger=ledger)
    body = json.dumps(
        {
            "id": "evt_invoice_checkout_pi_succeeded",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_invoice_checkout",
                    "amount": 6_000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "invoice_id": "inv-checkout-pi",
                        "parent_id": "parent-checkout",
                        "source": "invoice_pay_link",
                    },
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert ledger.invoices["inv-checkout-pi"].status == "open"
    assert ledger.invoices["inv-checkout-pi"].balance_due_cents == 6_000
    assert ledger.payments == {}
    assert ledger.allocations == []


@pytest.mark.asyncio
async def test_balance_checkout_completed_allocates_across_all_invoice_ids() -> None:
    repo = FakePaymentRepo()
    first = _ledger_invoice(
        invoice_id="inv-balance-1",
        parent_id="parent-balance",
        balance_due_cents=4_000,
    )
    second = _ledger_invoice(
        invoice_id="inv-balance-2",
        parent_id="parent-balance",
        balance_due_cents=6_000,
    )
    ledger = FakeBillingLedger(first)
    ledger.invoices[second.invoice_id] = second
    uc = _build(repo, billing_ledger=ledger)
    body = json.dumps(
        {
            "id": "evt_balance_checkout_completed",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_balance",
                    "payment_intent": "pi_balance",
                    "amount_total": 10_000,
                    "currency": "usd",
                    "metadata": {
                        "academy_id": "acad",
                        "parent_id": "parent-balance",
                        "invoice_ids": "inv-balance-1,inv-balance-2",
                        "type": "balance_payment",
                    },
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="worker-1")

    assert res["processed"] is True
    assert ledger.invoices["inv-balance-1"].status == "paid"
    assert ledger.invoices["inv-balance-1"].balance_due_cents == 0
    assert ledger.invoices["inv-balance-2"].status == "paid"
    assert ledger.invoices["inv-balance-2"].balance_due_cents == 0
    assert list(ledger.payments) == ["ledger-pay-cs:cs_balance"]
    assert ledger.payments["ledger-pay-cs:cs_balance"].stripe_payment_intent_id == "pi_balance"
    assert ledger.payments["ledger-pay-cs:cs_balance"].unapplied_amount_cents == 0
    assert ledger.allocations == [
        {
            "payment_id": "ledger-pay-cs:cs_balance",
            "invoice_id": "inv-balance-1",
            "amount_cents": 4_000,
            "idempotency_key": "invoice-checkout-alloc:cs_balance:inv-balance-1",
        },
        {
            "payment_id": "ledger-pay-cs:cs_balance",
            "invoice_id": "inv-balance-2",
            "amount_cents": 6_000,
            "idempotency_key": "invoice-checkout-alloc:cs_balance:inv-balance-2",
        },
    ]


@pytest.mark.asyncio
async def test_balance_checkout_validates_academy_before_recording_payment() -> None:
    """P0-1: a balance checkout.session.completed whose target invoice belongs to another
    academy must be quarantined BEFORE any ledger payment is recorded (validation-before-
    mutation), matching the autopay handler's ordering."""
    foreign_invoice = _ledger_invoice(
        invoice_id="inv-foreign", academy_id="other-acad", parent_id="parent-1"
    )
    ledger = FakeBillingLedger(foreign_invoice)
    uc = _build(FakePaymentRepo(), billing_ledger=ledger)  # handler academy_id="acad"

    event = {
        "id": "evt_balance_xtenant",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_balance_xtenant",
                "metadata": {
                    "invoice_ids": "inv-foreign",
                    "parent_id": "parent-1",
                    "type": "balance_payment",
                },
                "amount_total": 10_000,
                "currency": "usd",
                "payment_intent": "pi_xtenant",
            }
        },
    }

    with pytest.raises(_QuarantineStripeEvent):
        await uc._handle_balance_checkout_completed(event)

    # The cross-tenant event must be rejected WITHOUT recording any ledger payment.
    assert ledger.payments == {}
    assert ledger.allocations == []


@pytest.mark.asyncio
async def test_checkout_completed_marks_payment_succeeded_and_emits_event() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    body = json.dumps(
        {
            "id": "evt_1",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "payment_intent": "pi_1"}},
        }
    ).encode()
    res = await uc.execute(body, "test_signature")
    assert res["received"] is True
    assert repo.by_id["pay-1"].status == "succeeded"
    assert repo.by_id["pay-1"].stripe_payment_intent_id == "pi_1"
    assert [e.name for e in outbox.events] == ["Billing.PaymentSucceeded"]


@pytest.mark.asyncio
async def test_subscription_checkout_without_mapping_does_not_save_parent_stripe_customer() -> None:
    repo = FakePaymentRepo()
    customers = FakeParentStripeCustomers()
    uc = _build(repo, parent_customers=customers)
    body = json.dumps(
        {
            "id": "evt_subscription_checkout",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_subscription",
                    "customer": "cus_live_parent",
                    "subscription": "sub_live_parent",
                    "client_reference_id": "p1",
                    "metadata": {"parent_id": "p1", "subscription_id": "sub-1"},
                }
            },
        }
    ).encode()

    res = await uc.execute(body, "test_signature")

    assert res["received"] is True
    assert customers.saved == []


@pytest.mark.asyncio
async def test_dedup_short_circuits_replays() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_2",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1"}},
        }
    ).encode()
    await uc.execute(body, "test_signature")
    res = await uc.execute(body, "test_signature")
    assert res.get("deduped") is True


@pytest.mark.asyncio
async def test_checkout_expired_transitions_pending_to_expired() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    body = json.dumps(
        {
            "id": "evt_3",
            "type": "checkout.session.expired",
            "data": {"object": {"id": "cs_1"}},
        }
    ).encode()
    await uc.execute(body, "test_signature")
    assert repo.by_id["pay-1"].status == "expired"
    assert [e.name for e in outbox.events] == ["Billing.CheckoutExpired"]


@pytest.mark.asyncio
async def test_payment_failed_marks_failed_and_emits() -> None:
    repo = FakePaymentRepo()
    p = _seed_pending_payment(repo)
    repo.seed(p.model_copy(update={"stripe_payment_intent_id": "pi_x"}))
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    body = json.dumps(
        {
            "id": "evt_4",
            "type": "payment_intent.payment_failed",
            "data": {"object": {"id": "pi_x", "last_payment_error": {"message": "card declined"}}},
        }
    ).encode()
    await uc.execute(body, "test_signature")
    assert repo.by_id["pay-1"].status == "failed"
    assert outbox.events[0].name == "Billing.PaymentFailed"


@pytest.mark.asyncio
async def test_invoice_paid_creates_subscription_payment_and_emits() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-1",
            academy_id="acad",
            parent_id="p1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-1",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox, subscriptions=subs)
    body = json.dumps(
        {
            "id": "evt_invoice_1",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_1",
                    "subscription": "stripe-sub-1",
                    "payment_intent": "pi_invoice_1",
                    "amount_paid": 16000,
                    "currency": "usd",
                }
            },
        }
    ).encode()
    await uc.execute(body, "test_signature")
    payment = repo.by_pi["pi_invoice_1"]
    assert payment.status == "succeeded"
    assert payment.subscription_id == "sub-1"
    assert payment.session_id == "s1"
    assert outbox.events[0].name == "Billing.PaymentSucceeded"


@pytest.mark.asyncio
async def test_invoice_paid_reads_subscription_from_parent_details() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-parent-shape",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-parent",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    uc = _build(repo, subscriptions=subs)
    body = json.dumps(
        {
            "id": "evt_invoice_parent_shape",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_parent_shape",
                    "parent": {
                        "subscription_details": {
                            "subscription": "stripe-sub-parent",
                        }
                    },
                    "payment_intent": "pi_parent_shape",
                    "amount_paid": 7000,
                    "currency": "usd",
                }
            },
        }
    ).encode()

    await uc.execute(body, "test_signature")

    payment = repo.by_pi["pi_parent_shape"]
    assert payment.status == "succeeded"
    assert payment.subscription_id == "sub-parent-shape"
    assert payment.enrollment_id == "enr-1"
    assert payment.session_id == "s1"


@pytest.mark.asyncio
async def test_subscription_invoice_paid_allocates_existing_ledger_invoice() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-ledger",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-ledger",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-monthly-enr-1-2026-06",
            parent_id="p1",
            student_id="student-1",
            enrollment_id="enr-1",
            period="2026-06",
            balance_due_cents=7_000,
        )
    )
    uc = _build(repo, subscriptions=subs, billing_ledger=ledger)

    await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_paid_ledger",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_ledger",
                        "parent": {
                            "subscription_details": {
                                "subscription": "stripe-sub-ledger",
                            }
                        },
                        "payment_intent": "pi_ledger",
                        "amount_paid": 7_000,
                        "amount_due": 7_000,
                        "currency": "usd",
                        "period_start": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert ledger.invoices["inv-monthly-enr-1-2026-06"].status == "paid"
    assert ledger.invoices["inv-monthly-enr-1-2026-06"].balance_due_cents == 0
    assert ledger.payments["ledger-pay-in_ledger"].stripe_payment_intent_id == "pi_ledger"
    assert ledger.allocations == [
        {
            "payment_id": "ledger-pay-in_ledger",
            "invoice_id": "inv-monthly-enr-1-2026-06",
            "amount_cents": 7000,
            "idempotency_key": "stripe-invoice-allocation:in_ledger",
        }
    ]
    assert repo.by_pi["pi_ledger"].enrollment_id == "enr-1"


@pytest.mark.asyncio
async def test_subscription_invoice_paid_with_null_payment_intent_uses_invoice_id_for_idempotency() -> (
    None
):
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-api-2026",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-api-2026",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-monthly-enr-1-2026-06",
            parent_id="p1",
            enrollment_id="enr-1",
            period="2026-06",
            balance_due_cents=7_000,
        )
    )
    uc = _build(repo, subscriptions=subs, billing_ledger=ledger)

    await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_paid_api_2026",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_api_2026",
                        "parent": {
                            "subscription_details": {
                                "subscription": "stripe-sub-api-2026",
                            }
                        },
                        "payment_intent": None,
                        "amount_paid": 7_000,
                        "amount_due": 7_000,
                        "currency": "usd",
                        "period_start": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert repo.by_pi["in_api_2026"].status == "succeeded"
    assert ledger.payments["ledger-pay-in_api_2026"].stripe_payment_intent_id == "in_api_2026"
    assert ledger.payments["ledger-pay-in_api_2026"].stripe_invoice_id == "in_api_2026"
    assert ledger.invoices["inv-monthly-enr-1-2026-06"].balance_due_cents == 0
    assert ledger.invoices["inv-monthly-enr-1-2026-06"].stripe_invoice_id == "in_api_2026"


@pytest.mark.asyncio
async def test_subscription_invoice_paid_replay_does_not_duplicate_ledger_payment_or_allocation() -> (
    None
):
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-replay",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-replay",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-monthly-enr-1-2026-06",
            parent_id="p1",
            enrollment_id="enr-1",
            period="2026-06",
            balance_due_cents=7_000,
        )
    )
    uc = _build(repo, subscriptions=subs, billing_ledger=ledger)

    invoice_object = {
        "id": "in_replay",
        "subscription": "stripe-sub-replay",
        "payment_intent": None,
        "amount_paid": 7_000,
        "amount_due": 7_000,
        "currency": "usd",
        "period_start": 1_781_712_000,
    }
    for event_id in ("evt_invoice_paid_replay_1", "evt_invoice_paid_replay_2"):
        await uc.execute(
            json.dumps(
                {
                    "id": event_id,
                    "type": "invoice.paid",
                    "data": {"object": invoice_object},
                }
            ).encode(),
            "test_signature",
        )

    assert len(repo.by_id) == 1
    assert len(ledger.payments) == 1
    assert len(ledger.allocations) == 1
    assert ledger.invoices["inv-monthly-enr-1-2026-06"].status == "paid"


@pytest.mark.asyncio
async def test_payment_intent_succeeded_before_subscription_invoice_paid_waits_for_invoice_event() -> (
    None
):
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-out-of-order",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-out-of-order",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-monthly-enr-1-2026-06",
            parent_id="p1",
            enrollment_id="enr-1",
            period="2026-06",
            balance_due_cents=7_000,
        )
    )
    uc = _build(repo, subscriptions=subs, billing_ledger=ledger)

    await uc.execute(
        json.dumps(
            {
                "id": "evt_pi_before_invoice",
                "type": "payment_intent.succeeded",
                "data": {"object": {"id": "pi_out_of_order"}},
            }
        ).encode(),
        "test_signature",
    )

    assert repo.by_id == {}
    assert ledger.payments == {}

    await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_after_pi",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_out_of_order",
                        "subscription": "stripe-sub-out-of-order",
                        "payment_intent": "pi_out_of_order",
                        "amount_paid": 7_000,
                        "amount_due": 7_000,
                        "currency": "usd",
                        "period_start": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert len(repo.by_id) == 1
    assert len(ledger.payments) == 1
    assert (
        ledger.payments["ledger-pay-in_out_of_order"].stripe_payment_intent_id == "pi_out_of_order"
    )
    assert len(ledger.allocations) == 1


@pytest.mark.asyncio
async def test_subscription_invoice_paid_without_app_invoice_is_quarantined() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    identity = FakeEnrollmentBillingIdentity()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-create-ledger",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-create-ledger",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    identity.seed(
        enrollment_id="enr-1",
        parent_id="p1",
        student_id="student-1",
        session_id="s1",
    )
    ledger = FakeBillingLedger()
    uc = _build(
        repo,
        subscriptions=subs,
        enrollment_identity=identity,
        billing_ledger=ledger,
    )

    result = await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_paid_create_ledger",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_create_ledger",
                        "subscription": "stripe-sub-create-ledger",
                        "payment_intent": None,
                        "amount_paid": 7_000,
                        "amount_due": 7_000,
                        "currency": "usd",
                        "period_start": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert result["status"] == "quarantined"
    assert "app-owned LedgerInvoice" in result["error"]
    assert ledger.invoices == {}
    assert ledger.lines == {}
    assert ledger.payments == {}
    assert ledger.allocations == []


@pytest.mark.asyncio
async def test_subscription_invoice_paid_different_invoice_for_paid_obligation_is_quarantined() -> (
    None
):
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-paid-duplicate",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-paid-duplicate",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-monthly-enr-1-2026-06",
            parent_id="p1",
            student_id="student-1",
            enrollment_id="enr-1",
            period="2026-06",
            balance_due_cents=0,
            status="paid",
        ).model_copy(update={"stripe_invoice_id": "in_original"})
    )
    dedup = FakeDedup()
    uc = _build(repo, subscriptions=subs, billing_ledger=ledger, dedup=dedup)

    result = await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_paid_duplicate_obligation",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_duplicate_obligation",
                        "subscription": "stripe-sub-paid-duplicate",
                        "payment_intent": None,
                        "amount_paid": 7_000,
                        "amount_due": 7_000,
                        "currency": "usd",
                        "period_start": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert result["status"] == "quarantined"
    assert "already-paid invoice" in result["error"]
    assert set(ledger.invoices) == {"inv-monthly-enr-1-2026-06"}
    assert ledger.payments == {}
    assert ledger.allocations == []
    assert repo.by_id == {}


@pytest.mark.asyncio
async def test_subscription_invoice_paid_zero_amount_does_not_create_ledger_payment_or_allocation() -> (
    None
):
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-zero",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-zero",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    ledger = FakeBillingLedger()
    uc = _build(repo, subscriptions=subs, billing_ledger=ledger)

    await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_paid_zero",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_zero",
                        "subscription": "stripe-sub-zero",
                        "payment_intent": None,
                        "amount_paid": 0,
                        "amount_due": 0,
                        "currency": "usd",
                        "period_start": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert ledger.payments == {}
    assert ledger.allocations == []


@pytest.mark.asyncio
async def test_subscription_invoice_paid_quarantines_enrollment_parent_mismatch() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    identity = FakeEnrollmentBillingIdentity()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-parent-mismatch",
            academy_id="acad",
            parent_id="subscription-parent",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-parent-mismatch",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    identity.seed(
        enrollment_id="enr-1",
        parent_id="different-parent",
        student_id="student-1",
        session_id="s1",
    )
    ledger = FakeBillingLedger()
    dedup = FakeDedup()
    uc = _build(
        repo,
        subscriptions=subs,
        enrollment_identity=identity,
        billing_ledger=ledger,
        dedup=dedup,
    )

    result = await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_paid_parent_mismatch",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_parent_mismatch",
                        "subscription": "stripe-sub-parent-mismatch",
                        "payment_intent": None,
                        "amount_paid": 7_000,
                        "amount_due": 7_000,
                        "currency": "usd",
                        "period_start": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert result["status"] == "quarantined"
    assert "parent mismatch" in result["error"]
    assert ledger.payments == {}
    assert ledger.allocations == []


@pytest.mark.asyncio
async def test_invoice_payment_failed_creates_failed_subscription_payment() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-2",
            academy_id="acad",
            parent_id="p1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-2",
            status="past_due",
            created_at=now,
            updated_at=now,
        )
    )
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox, subscriptions=subs)
    body = json.dumps(
        {
            "id": "evt_invoice_2",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_2",
                    "subscription": "stripe-sub-2",
                    "payment_intent": "pi_invoice_2",
                    "amount_due": 16000,
                    "currency": "usd",
                    "last_finalization_error": {"message": "card declined"},
                }
            },
        }
    ).encode()
    await uc.execute(body, "test_signature")
    payment = repo.by_pi["pi_invoice_2"]
    assert payment.status == "failed"
    assert payment.subscription_id == "sub-2"
    assert outbox.events[0].name == "Billing.PaymentFailed"


@pytest.mark.asyncio
async def test_subscription_invoice_payment_failed_without_app_invoice_is_quarantined() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-failed-ledger",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-failed-ledger",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    ledger = FakeBillingLedger()
    uc = _build(repo, subscriptions=subs, billing_ledger=ledger)

    result = await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_failed_ledger",
                "type": "invoice.payment_failed",
                "data": {
                    "object": {
                        "id": "in_failed_ledger",
                        "subscription": "stripe-sub-failed-ledger",
                        "payment_intent": "pi_failed_ledger",
                        "amount_due": 7_000,
                        "currency": "usd",
                        "period_start": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert result["status"] == "quarantined"
    assert "app-owned LedgerInvoice" in result["error"]
    assert ledger.invoices == {}
    assert ledger.payments == {}
    assert ledger.allocations == []


@pytest.mark.asyncio
async def test_subscription_invoice_paid_retry_after_ledger_payment_before_allocation_resumes_without_duplicate_payment() -> (
    None
):
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-retry-payment",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-retry-payment",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-monthly-enr-1-2026-06",
            parent_id="p1",
            student_id="student-1",
            enrollment_id="enr-1",
            period="2026-06",
            balance_due_cents=7_000,
        )
    )
    ledger.fail_allocate = True
    processing = FakeInvoiceProcessing()
    uc = _build(
        repo,
        subscriptions=subs,
        billing_ledger=ledger,
        invoice_processing=processing,
    )
    event_object = {
        "id": "in_retry_after_payment",
        "subscription": "stripe-sub-retry-payment",
        "payment_intent": None,
        "amount_paid": 7_000,
        "amount_due": 7_000,
        "currency": "usd",
        "period_start": 1_781_712_000,
    }

    with pytest.raises(ValueError, match="allocation failed"):
        await uc.execute(
            json.dumps(
                {
                    "id": "evt_retry_after_payment_1",
                    "type": "invoice.paid",
                    "data": {"object": event_object},
                }
            ).encode(),
            "test_signature",
        )

    assert len(ledger.payments) == 1
    assert ledger.allocations == []
    row = processing.by_key["acad:stripe_invoice:in_retry_after_payment"]
    assert row["recovery_point"] == "ledger_payment_recorded"

    ledger.fail_allocate = False
    await uc.execute(
        json.dumps(
            {
                "id": "evt_retry_after_payment_2",
                "type": "invoice.paid",
                "data": {"object": event_object},
            }
        ).encode(),
        "test_signature",
    )

    assert len(ledger.payments) == 1
    assert len(ledger.allocations) == 1
    assert len(repo.by_id) == 1
    row = processing.by_key["acad:stripe_invoice:in_retry_after_payment"]
    assert row["recovery_point"] == "processed"
    assert row["event_ids"] == ["evt_retry_after_payment_1", "evt_retry_after_payment_2"]


@pytest.mark.asyncio
async def test_subscription_invoice_paid_retry_after_allocation_before_legacy_projection_resumes_without_duplicate_allocation() -> (
    None
):
    repo = FakePaymentRepo()
    repo.fail_next_save = True
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subs.seed(
        Subscription(
            subscription_id="sub-retry-allocation",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-retry-allocation",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-monthly-enr-1-2026-06",
            parent_id="p1",
            student_id="student-1",
            enrollment_id="enr-1",
            period="2026-06",
            balance_due_cents=7_000,
        )
    )
    processing = FakeInvoiceProcessing()
    uc = _build(
        repo,
        subscriptions=subs,
        billing_ledger=ledger,
        invoice_processing=processing,
    )
    event_object = {
        "id": "in_retry_after_allocation",
        "subscription": "stripe-sub-retry-allocation",
        "payment_intent": None,
        "amount_paid": 7_000,
        "amount_due": 7_000,
        "currency": "usd",
        "period_start": 1_781_712_000,
    }

    with pytest.raises(RuntimeError, match="transient payment write failed"):
        await uc.execute(
            json.dumps(
                {
                    "id": "evt_retry_after_allocation_1",
                    "type": "invoice.paid",
                    "data": {"object": event_object},
                }
            ).encode(),
            "test_signature",
        )

    assert len(ledger.payments) == 1
    assert len(ledger.allocations) == 1
    assert repo.by_id == {}
    row = processing.by_key["acad:stripe_invoice:in_retry_after_allocation"]
    assert row["recovery_point"] == "ledger_allocated"

    await uc.execute(
        json.dumps(
            {
                "id": "evt_retry_after_allocation_2",
                "type": "invoice.paid",
                "data": {"object": event_object},
            }
        ).encode(),
        "test_signature",
    )

    assert len(ledger.payments) == 1
    assert len(ledger.allocations) == 1
    assert len(repo.by_id) == 1
    row = processing.by_key["acad:stripe_invoice:in_retry_after_allocation"]
    assert row["recovery_point"] == "processed"
    assert row["event_ids"] == [
        "evt_retry_after_allocation_1",
        "evt_retry_after_allocation_2",
    ]


@pytest.mark.asyncio
async def test_invoice_paid_does_not_downgrade_refunded_projection_to_succeeded() -> None:
    repo = FakePaymentRepo()
    now = datetime.now(UTC)
    repo.seed(
        Payment(
            payment_id="pay-refunded",
            academy_id="acad",
            parent_id="p1",
            subscription_id="sub-1",
            stripe_payment_intent_id="in_refunded_projection",
            amount_cents=7_000,
            status="refunded",
            refunded_cents=7_000,
            created_at=now,
            updated_at=now,
        )
    )
    subs = FakeSubscriptionRepo()
    subs.seed(
        Subscription(
            subscription_id="sub-1",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-refunded-projection",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    uc = _build(repo, subscriptions=subs)

    result = await uc.execute(
        json.dumps(
            {
                "id": "evt_refunded_projection_paid",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_refunded_projection",
                        "subscription": "stripe-sub-refunded-projection",
                        "payment_intent": None,
                        "amount_paid": 7_000,
                        "amount_due": 7_000,
                        "currency": "usd",
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert result["status"] == "quarantined"
    assert "invalid payment projection transition refunded->succeeded" in result["error"]
    assert repo.by_id["pay-refunded"].status == "refunded"


@pytest.mark.asyncio
async def test_invoice_payment_failed_does_not_downgrade_succeeded_projection_to_failed() -> None:
    repo = FakePaymentRepo()
    now = datetime.now(UTC)
    repo.seed(
        Payment(
            payment_id="pay-succeeded",
            academy_id="acad",
            parent_id="p1",
            subscription_id="sub-1",
            stripe_payment_intent_id="pi_succeeded_projection",
            amount_cents=7_000,
            status="succeeded",
            created_at=now,
            updated_at=now,
        )
    )
    subs = FakeSubscriptionRepo()
    subs.seed(
        Subscription(
            subscription_id="sub-1",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-succeeded-projection",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    uc = _build(repo, subscriptions=subs)

    result = await uc.execute(
        json.dumps(
            {
                "id": "evt_succeeded_projection_failed",
                "type": "invoice.payment_failed",
                "data": {
                    "object": {
                        "id": "in_succeeded_projection",
                        "subscription": "stripe-sub-succeeded-projection",
                        "payment_intent": "pi_succeeded_projection",
                        "amount_due": 7_000,
                        "currency": "usd",
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert result["status"] == "quarantined"
    assert "invalid payment projection transition succeeded->failed" in result["error"]
    assert repo.by_id["pay-succeeded"].status == "succeeded"


@pytest.mark.asyncio
async def test_charge_refunded_updates_cumulative_amount() -> None:
    repo = FakePaymentRepo()
    p = _seed_pending_payment(repo)
    repo.seed(p.model_copy(update={"stripe_payment_intent_id": "pi_y", "status": "succeeded"}))
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    body = json.dumps(
        {
            "id": "evt_5",
            "type": "charge.refunded",
            "data": {"object": {"payment_intent": "pi_y", "amount_refunded": 5000}},
        }
    ).encode()
    await uc.execute(body, "test_signature")
    assert repo.by_id["pay-1"].refunded_cents == 5000
    assert repo.by_id["pay-1"].status == "partially_refunded"


def _seed_ledger_payment(
    ledger: FakeBillingLedger,
    *,
    pi: str,
    payment_id: str = "ledger-pay-1",
    amount_cents: int = 10_000,
    status: str = "succeeded",
) -> LedgerPayment:
    now = datetime.now(UTC)
    payment = LedgerPayment(
        payment_id=payment_id,
        academy_id="acad",
        parent_id="parent-1",
        amount_cents=amount_cents,
        unapplied_amount_cents=amount_cents,
        currency="usd",
        status=status,  # type: ignore[arg-type]
        payment_method="stripe_autopay",
        stripe_payment_intent_id=pi,
        paid_at=now,
        created_at=now,
        updated_at=now,
    )
    ledger.payments[payment.payment_id] = payment
    return payment


def _charge_refunded_body(event_id: str, pi: str, amount_refunded: int) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": "charge.refunded",
            "data": {"object": {"payment_intent": pi, "amount_refunded": amount_refunded}},
        }
    ).encode()


@pytest.mark.asyncio
async def test_charge_refunded_records_full_refund_for_ledger_only_payment() -> None:
    """Regression: a charge recorded only in the ledger (autopay / invoice
    pay-link / balance checkout) must have its refund recorded, not silently
    dropped because the legacy `payments` collection has no matching row."""
    repo = FakePaymentRepo()  # legacy repo has NO row for this PI
    ledger = FakeBillingLedger()
    _seed_ledger_payment(ledger, pi="pi_ledger_full", amount_cents=10_000)
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox, billing_ledger=ledger)

    await uc.execute(
        _charge_refunded_body("evt_ledger_full", "pi_ledger_full", 10_000),
        "test_signature",
    )

    refunded = ledger.payments["ledger-pay-1"]
    assert refunded.status == "refunded"
    assert refunded.refunded_cents == 10_000
    assert any(type(e).__name__ == "PaymentRefunded" for e in outbox.events)


@pytest.mark.asyncio
async def test_charge_refunded_ledger_partial_then_idempotent() -> None:
    """Partial refund of a ledger-only payment is recorded as
    partially_refunded; a resent webhook with the same cumulative total is a
    no-op (no double event, no further mutation)."""
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger()
    _seed_ledger_payment(ledger, pi="pi_ledger_partial", amount_cents=10_000)
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox, billing_ledger=ledger)

    await uc.execute(
        _charge_refunded_body("evt_partial_1", "pi_ledger_partial", 4_000),
        "test_signature",
    )
    after_first = ledger.payments["ledger-pay-1"]
    assert after_first.status == "partially_refunded"
    assert after_first.refunded_cents == 4_000
    events_after_first = len(outbox.events)

    # Stripe re-delivers the same refund total — must be idempotent.
    await uc.execute(
        _charge_refunded_body("evt_partial_1b", "pi_ledger_partial", 4_000),
        "test_signature",
    )
    assert ledger.payments["ledger-pay-1"].refunded_cents == 4_000
    assert len(outbox.events) == events_after_first


def _seed_incomplete_subscription(
    subs: FakeSubscriptionRepo,
    *,
    stripe_subscription_id: str = "",
    status: str = "incomplete",
) -> Subscription:
    now = datetime.now(UTC)
    subscription = Subscription(
        subscription_id="sub-1",
        academy_id="acad",
        parent_id="p1",
        enrollment_id="enr-1",
        session_id="s1",
        stripe_subscription_id=stripe_subscription_id,
        status=status,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
    )
    subs.seed(subscription)
    return subscription


@pytest.mark.asyncio
async def test_subscription_checkout_completed_activates_subscription_and_enrollment() -> None:
    """Checkout completion must backfill the Stripe subscription id (null at
    checkout-creation time) and flip both the subscription row and the
    enrollment's autopay state to active — otherwise parents stay stuck at
    'incomplete' forever."""
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    _seed_incomplete_subscription(subs)
    enrollment_autopay = FakeEnrollmentAutopayState()
    uc = _build(repo, subscriptions=subs, enrollment_autopay=enrollment_autopay)
    body = json.dumps(
        {
            "id": "evt_sub_checkout_done",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_sub_1",
                    "customer": "cus_live_parent",
                    "subscription": "sub_live_1",
                    "metadata": {
                        "parent_id": "p1",
                        "subscription_id": "sub-1",
                        "enrollment_id": "enr-1",
                    },
                }
            },
        }
    ).encode()

    await uc.execute(body, "test_signature")

    updated = subs.by_stripe_sub["sub_live_1"]
    assert updated.subscription_id == "sub-1"
    assert updated.status == "active"
    assert enrollment_autopay.setup_completed == ["enr-1"]
    assert enrollment_autopay.synced == []


@pytest.mark.asyncio
async def test_checkout_completed_binds_stripe_id_to_its_own_pending_subscription() -> None:
    """Two pending rows for one enrollment: completion must attach the Stripe
    id to the row named in the checkout's metadata.subscription_id, not to
    whichever row is newest for the enrollment."""
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    first = Subscription(
        subscription_id="sub-first",
        academy_id="acad",
        parent_id="p1",
        enrollment_id="enr-1",
        session_id="s1",
        stripe_subscription_id="",
        status="incomplete",
        created_at=now,
        updated_at=now,
    )
    newer = first.model_copy(update={"subscription_id": "sub-newer"})
    subs.seed(first)
    subs.seed(newer)  # latest_for_enrollment would return this one
    enrollment_autopay = FakeEnrollmentAutopayState()
    uc = _build(repo, subscriptions=subs, enrollment_autopay=enrollment_autopay)
    body = json.dumps(
        {
            "id": "evt_sub_checkout_first",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_first",
                    "customer": "cus_live_parent",
                    "subscription": "sub_live_first",
                    "metadata": {
                        "parent_id": "p1",
                        "subscription_id": "sub-first",
                        "enrollment_id": "enr-1",
                    },
                }
            },
        }
    ).encode()

    await uc.execute(body, "test_signature")

    bound = subs.by_stripe_sub["sub_live_first"]
    assert bound.subscription_id == "sub-first"
    assert bound.status == "active"
    # The unrelated newer pending row must remain untouched.
    assert subs.by_id["sub-newer"].stripe_subscription_id == ""
    assert subs.by_id["sub-newer"].status == "incomplete"


@pytest.mark.asyncio
async def test_subscription_updated_syncs_enrollment_autopay_state() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    _seed_incomplete_subscription(subs, stripe_subscription_id="sub_live_9", status="active")
    enrollment_autopay = FakeEnrollmentAutopayState()
    uc = _build(repo, subscriptions=subs, enrollment_autopay=enrollment_autopay)
    body = json.dumps(
        {
            "id": "evt_sub_updated",
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_live_9", "status": "past_due"}},
        }
    ).encode()

    await uc.execute(body, "test_signature")

    assert subs.by_stripe_sub["sub_live_9"].status == "past_due"
    assert enrollment_autopay.synced == [
        {
            "enrollment_id": "enr-1",
            "autopay_enrollment_status": "active",
        }
    ]


@pytest.mark.asyncio
async def test_stale_subscription_event_does_not_flip_converged_enrollment() -> None:
    """HIGH review-fix #4: once an enrollment has converged onto app-owned
    autopay (its stripe_subscription_id is cleared), a stale/duplicate legacy
    subscription webhook must NOT flip its autopay status."""
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    _seed_incomplete_subscription(subs, stripe_subscription_id="sub_live_9", status="active")
    enrollment_autopay = FakeEnrollmentAutopayState()
    # Billing enrollment has converged: no stripe_subscription_id any more.
    billing_enrollments = _FakeBillingEnrollmentsForGuard(
        enrollment_id="enr-1", stripe_subscription_id=None
    )
    uc = _build(
        repo,
        subscriptions=subs,
        enrollment_autopay=enrollment_autopay,
        billing_enrollments=billing_enrollments,
    )
    body = json.dumps(
        {
            "id": "evt_sub_stale",
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_live_9", "status": "canceled"}},
        }
    ).encode()

    await uc.execute(body, "test_signature")

    # Subscription row still reconciles, but the converged enrollment's autopay
    # status is left untouched.
    assert subs.by_stripe_sub["sub_live_9"].status == "cancelled"
    assert enrollment_autopay.synced == []


@pytest.mark.asyncio
async def test_subscription_event_converges_when_still_subscription_managed() -> None:
    """Complement to the guard: when the billing enrollment still carries the
    matching stripe_subscription_id, convergence still runs (through the guard)."""
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    _seed_incomplete_subscription(subs, stripe_subscription_id="sub_live_9", status="active")
    enrollment_autopay = FakeEnrollmentAutopayState()
    billing_enrollments = _FakeBillingEnrollmentsForGuard(
        enrollment_id="enr-1", stripe_subscription_id="sub_live_9"
    )
    uc = _build(
        repo,
        subscriptions=subs,
        enrollment_autopay=enrollment_autopay,
        billing_enrollments=billing_enrollments,
    )
    body = json.dumps(
        {
            "id": "evt_sub_managed",
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_live_9", "status": "past_due"}},
        }
    ).encode()

    await uc.execute(body, "test_signature")

    assert enrollment_autopay.synced == [
        {"enrollment_id": "enr-1", "autopay_enrollment_status": "active"}
    ]


@pytest.mark.asyncio
async def test_subscription_deleted_syncs_enrollment_cancelled() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    _seed_incomplete_subscription(subs, stripe_subscription_id="sub_live_9", status="active")
    enrollment_autopay = FakeEnrollmentAutopayState()
    uc = _build(repo, subscriptions=subs, enrollment_autopay=enrollment_autopay)
    body = json.dumps(
        {
            "id": "evt_sub_deleted",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_live_9", "status": "canceled"}},
        }
    ).encode()

    await uc.execute(body, "test_signature")

    assert subs.by_stripe_sub["sub_live_9"].status == "cancelled"
    assert enrollment_autopay.synced == [
        {
            "enrollment_id": "enr-1",
            "autopay_enrollment_status": "disabled",
        }
    ]


@pytest.mark.asyncio
async def test_unknown_event_type_is_ignored() -> None:
    repo = FakePaymentRepo()
    uc = _build(repo)
    body = json.dumps(
        {
            "id": "evt_6",
            "type": "customer.created",
            "data": {"object": {}},
        }
    ).encode()
    res = await uc.execute(body, "test_signature")
    assert res["received"] is True


# ---------------------------------------------------------------------------
# Autopay opt-in at payment time (checkout.session.completed, mode=payment)
# ---------------------------------------------------------------------------


class _OptinFakeStripeGateway(FakeStripeGateway):
    """FakeStripeGateway with resolvable PaymentIntents for opt-in payments."""

    def __init__(self, *, payment_intent_error: Exception | None = None) -> None:
        super().__init__()
        self.payment_intent_objects: dict[str, dict[str, Any]] = {}
        self._payment_intent_error = payment_intent_error

    async def retrieve_payment_intent(self, stripe_payment_intent_id: str) -> dict[str, Any]:
        if self._payment_intent_error is not None:
            raise self._payment_intent_error
        stored = self.payment_intent_objects.get(stripe_payment_intent_id)
        if stored is not None:
            return dict(stored)
        return await super().retrieve_payment_intent(stripe_payment_intent_id)


def _optin_stripe(*, payment_intent_error: Exception | None = None) -> _OptinFakeStripeGateway:
    stripe = _OptinFakeStripeGateway(payment_intent_error=payment_intent_error)
    stripe.payment_intent_objects["pi_optin"] = {
        "id": "pi_optin",
        "object": "payment_intent",
        "customer": "cus_optin_parent",
        "payment_method": "pm_optin",
    }
    stripe.payment_methods["pm_optin"] = {
        "id": "pm_optin",
        "object": "payment_method",
        "type": "card",
        "card": {"brand": "visa", "last4": "4242"},
    }
    return stripe


def _optin_invoice_checkout_event(
    *,
    event_id: str = "evt_optin_invoice",
    session_id: str = "cs_optin_invoice",
    metadata: dict[str, str],
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": session_id,
                    "mode": "payment",
                    "payment_intent": "pi_optin",
                    "amount_total": 10_000,
                    "currency": "usd",
                    "customer": "cus_optin_parent",
                    "metadata": metadata,
                }
            },
        }
    ).encode()


@pytest.mark.asyncio
async def test_invoice_checkout_completed_with_autopay_optin_activates_enrollment() -> None:
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-optin",
            parent_id="parent-optin",
            balance_due_cents=10_000,
            enrollment_id="enr-1",
        )
    )
    parent_customers = FakeParentStripeCustomers()
    enrollment_autopay = FakeEnrollmentAutopayState()
    consent_repo = FakeAutopayConsentRepo()
    uc = _build(
        FakePaymentRepo(),
        billing_ledger=ledger,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consent_repo,
        stripe=_optin_stripe(),
    )
    body = _optin_invoice_checkout_event(
        metadata={
            "academy_id": "acad",
            "parent_id": "parent-optin",
            "invoice_id": "inv-optin",
            "source": "invoice_pay_link",
            "autopay_optin": "true",
            "enrollment_ids": "enr-1",
        },
    )

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="worker-1")

    assert res["processed"] is True
    # Ledger bookkeeping unchanged.
    assert ledger.invoices["inv-optin"].status == "paid"
    assert list(ledger.payments) == ["ledger-pay-cs:cs_optin_invoice"]
    # Autopay activated from the payment checkout.
    assert enrollment_autopay.setup_completed == ["enr-1"]
    assert len(consent_repo.consents) == 1
    assert consent_repo.consents[0].source == "invoice_payment_optin"
    assert parent_customers.default_methods


@pytest.mark.asyncio
async def test_balance_checkout_completed_with_autopay_optin_activates_all_enrollments() -> None:
    first = _ledger_invoice(
        invoice_id="inv-optin-1",
        parent_id="parent-optin",
        balance_due_cents=4_000,
        enrollment_id="enr-1",
    )
    second = _ledger_invoice(
        invoice_id="inv-optin-2",
        parent_id="parent-optin",
        balance_due_cents=6_000,
        enrollment_id="enr-2",
    )
    ledger = FakeBillingLedger(first)
    ledger.invoices[second.invoice_id] = second
    enrollment_autopay = FakeEnrollmentAutopayState()
    uc = _build(
        FakePaymentRepo(),
        billing_ledger=ledger,
        parent_customers=FakeParentStripeCustomers(),
        enrollment_autopay=enrollment_autopay,
        consent_repo=FakeAutopayConsentRepo(),
        stripe=_optin_stripe(),
    )
    body = _optin_invoice_checkout_event(
        event_id="evt_optin_balance",
        session_id="cs_optin_balance",
        metadata={
            "academy_id": "acad",
            "parent_id": "parent-optin",
            "invoice_ids": "inv-optin-1,inv-optin-2",
            "type": "balance_payment",
            "autopay_optin": "true",
            "enrollment_ids": "enr-1,enr-2",
        },
    )

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="worker-1")

    assert res["processed"] is True
    assert ledger.invoices["inv-optin-1"].status == "paid"
    assert ledger.invoices["inv-optin-2"].status == "paid"
    assert enrollment_autopay.setup_completed == ["enr-1", "enr-2"]


@pytest.mark.asyncio
async def test_invoice_checkout_optin_transient_activation_failure_retries() -> None:
    """A transient activation failure (e.g. Stripe retrieval blip) must mark
    the event failed so the worker retries it — never silently drop the
    opt-in after marking the event processed. Ledger bookkeeping is
    idempotent, so the replay both keeps the payment recorded once and
    completes the activation."""
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-optin",
            parent_id="parent-optin",
            balance_due_cents=10_000,
            enrollment_id="enr-1",
        )
    )
    enrollment_autopay = FakeEnrollmentAutopayState()
    stripe = _optin_stripe(payment_intent_error=RuntimeError("stripe unavailable"))
    uc = _build(
        FakePaymentRepo(),
        billing_ledger=ledger,
        parent_customers=FakeParentStripeCustomers(),
        enrollment_autopay=enrollment_autopay,
        consent_repo=FakeAutopayConsentRepo(),
        stripe=stripe,
    )
    body = _optin_invoice_checkout_event(
        metadata={
            "academy_id": "acad",
            "parent_id": "parent-optin",
            "invoice_id": "inv-optin",
            "source": "invoice_pay_link",
            "autopay_optin": "true",
            "enrollment_ids": "enr-1",
        },
    )

    await uc.accept(body, "test_signature")
    failed = await uc.process_next(processor_id="worker-1")

    # Event failed (retryable), ledger bookkeeping intact, no activation yet.
    assert failed["processed"] is False
    assert failed["status"] == "failed"
    assert ledger.invoices["inv-optin"].status == "paid"
    assert list(ledger.payments) == ["ledger-pay-cs:cs_optin_invoice"]
    assert enrollment_autopay.setup_completed == []

    # Stripe recovers; the retry replays the event idempotently and activates.
    stripe._payment_intent_error = None
    retried = await uc.process_next(processor_id="worker-1")

    assert retried["processed"] is True
    assert list(ledger.payments) == ["ledger-pay-cs:cs_optin_invoice"]
    assert enrollment_autopay.setup_completed == ["enr-1"]


@pytest.mark.asyncio
async def test_invoice_checkout_completed_without_optin_does_not_touch_autopay() -> None:
    ledger = FakeBillingLedger(
        _ledger_invoice(
            invoice_id="inv-optin",
            parent_id="parent-optin",
            balance_due_cents=10_000,
            enrollment_id="enr-1",
        )
    )
    parent_customers = FakeParentStripeCustomers()
    enrollment_autopay = FakeEnrollmentAutopayState()
    consent_repo = FakeAutopayConsentRepo()
    uc = _build(
        FakePaymentRepo(),
        billing_ledger=ledger,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consent_repo,
        stripe=_optin_stripe(),
    )
    body = _optin_invoice_checkout_event(
        metadata={
            "academy_id": "acad",
            "parent_id": "parent-optin",
            "invoice_id": "inv-optin",
            "source": "invoice_pay_link",
        },
    )

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="worker-1")

    assert res["processed"] is True
    assert ledger.invoices["inv-optin"].status == "paid"
    assert enrollment_autopay.setup_completed == []
    assert consent_repo.consents == []
    assert parent_customers.default_methods == []
