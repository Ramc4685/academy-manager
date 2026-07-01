from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerInvoice,
    LedgerPayment,
)
from backend.v2.contexts.billing.domain.session_type import StudentBillingEnrollment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.tests.application.test_webhook_handler import (
    FakeDedup,
    FakeOutbox,
    FakePaymentRepo,
    FakeSubscriptionRepo,
)


def _now() -> datetime:
    return datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


class FakeBillingEnrollmentRepo:
    def __init__(self) -> None:
        self.rows: dict[str, StudentBillingEnrollment] = {}

    def seed(self, enrollment: StudentBillingEnrollment) -> None:
        self.rows[enrollment.enrollment_id] = enrollment

    async def save(self, enrollment: StudentBillingEnrollment) -> None:
        self.rows[enrollment.enrollment_id] = enrollment

    async def get(self, enrollment_id: str) -> StudentBillingEnrollment | None:
        return self.rows.get(enrollment_id)

    async def list_for_student(self, student_id: str) -> list[StudentBillingEnrollment]:
        return [row for row in self.rows.values() if row.student_id == student_id]

    async def list_for_parent(self, parent_id: str) -> list[StudentBillingEnrollment]:
        return [row for row in self.rows.values() if row.parent_id == parent_id]

    async def get_by_stripe_subscription(
        self, stripe_subscription_id: str
    ) -> StudentBillingEnrollment | None:
        for row in self.rows.values():
            if row.stripe_subscription_id == stripe_subscription_id:
                return row
        return None


class FakeLedgerRepo:
    def __init__(self) -> None:
        self.invoices: dict[str, LedgerInvoice] = {}
        self.lines: dict[str, list[InvoiceLine]] = {}
        self.payments: dict[str, LedgerPayment] = {}
        self.allocations: list[dict[str, Any]] = []

    async def create_invoice(
        self,
        invoice: LedgerInvoice,
        *,
        lines: list[InvoiceLine],
        idempotency_key: str,
    ) -> LedgerInvoice:
        existing = self.invoices.get(invoice.invoice_id)
        if existing is not None:
            return existing
        self.invoices[invoice.invoice_id] = invoice
        self.lines[invoice.invoice_id] = lines
        return invoice

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self.invoices.get(invoice_id)

    async def record_payment(
        self,
        payment: LedgerPayment,
        *,
        idempotency_key: str,
    ) -> LedgerPayment:
        existing = self.payments.get(payment.payment_id)
        if existing is not None:
            return existing
        self.payments[payment.payment_id] = payment
        return payment

    async def allocate_payment(
        self,
        *,
        payment_id: str,
        invoice_id: str,
        amount_cents: int,
        idempotency_key: str,
    ):
        invoice = self.invoices[invoice_id]
        updated = invoice.model_copy(
            update={
                "status": "paid",
                "balance_due_cents": 0,
                "updated_at": _now(),
            }
        )
        self.invoices[invoice_id] = updated
        self.allocations.append(
            {
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "amount_cents": amount_cents,
                "idempotency_key": idempotency_key,
            }
        )


class FakeBillingCounterRepo:
    def __init__(self) -> None:
        self._seqs: dict[str, int] = {}

    async def next_value(self, *, scope: str) -> int:
        self._seqs[scope] = self._seqs.get(scope, 0) + 1
        return self._seqs[scope]


class FakeBillingSettingsRepo:
    def __init__(self, prefix: str = "BLNO") -> None:
        self._prefix = prefix

    async def get(self):
        from backend.v2.contexts.billing.domain.billing_settings import BillingSettings

        return BillingSettings(academy_id="acad", invoice_number_prefix=self._prefix)


def _build(
    *,
    payments=None,
    enrollments=None,
    ledger=None,
    outbox=None,
    counters=None,
    settings=None,
) -> HandleWebhookEvent:
    return HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=payments or FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        billing_enrollments=enrollments,
        billing_ledger=ledger,
        billing_counters=counters,
        billing_settings=settings,
        outbox=outbox or FakeOutbox(),
        academy_id="acad",
        clock=_now,
    )


@pytest.mark.asyncio
async def test_invoice_paid_for_session_type_subscription_writes_ledger_and_skips_legacy_payment() -> (
    None
):
    payments = FakePaymentRepo()
    enrollments = FakeBillingEnrollmentRepo()
    ledger = FakeLedgerRepo()
    outbox = FakeOutbox()
    enrollments.seed(
        StudentBillingEnrollment(
            enrollment_id="bill-1",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            session_type_id="type-elite",
            stripe_subscription_id="sub_123",
            billing_start_date=_now(),
            enrolled_at=_now(),
            updated_at=_now(),
        )
    )
    uc = _build(payments=payments, enrollments=enrollments, ledger=ledger, outbox=outbox)

    await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_paid_session_type",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_123",
                        "subscription": "sub_123",
                        "payment_intent": "pi_123",
                        "amount_paid": 20_000,
                        "amount_due": 20_000,
                        "currency": "usd",
                        "period_start": 1_779_120_000,
                        "period_end": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert payments.by_id == {}
    assert ledger.invoices["ledger-in_123"].status == "paid"
    assert ledger.invoices["ledger-in_123"].due_date == date(2026, 6, 19)
    assert ledger.lines["ledger-in_123"][0].source_type == "session_type"
    assert ledger.lines["ledger-in_123"][0].source_id == "type-elite"
    assert ledger.payments["ledger-pay-in_123"].stripe_payment_intent_id == "pi_123"
    assert ledger.allocations[0]["invoice_id"] == "ledger-in_123"
    assert [event.name for event in outbox.events] == ["Billing.InvoicePaid"]


@pytest.mark.asyncio
async def test_invoice_paid_for_session_type_subscription_mints_invoice_number() -> None:
    """Slice D: when billing_counters/billing_settings are wired, the ledger invoice
    created from a Stripe subscription invoice gets a minted invoice_number."""
    enrollments = FakeBillingEnrollmentRepo()
    ledger = FakeLedgerRepo()
    enrollments.seed(
        StudentBillingEnrollment(
            enrollment_id="bill-1",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            session_type_id="type-elite",
            stripe_subscription_id="sub_123",
            billing_start_date=_now(),
            enrolled_at=_now(),
            updated_at=_now(),
        )
    )
    uc = _build(
        enrollments=enrollments,
        ledger=ledger,
        counters=FakeBillingCounterRepo(),
        settings=FakeBillingSettingsRepo(prefix="ACAD"),
    )

    await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_paid_session_type_number",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_555",
                        "subscription": "sub_123",
                        "payment_intent": "pi_555",
                        "amount_paid": 20_000,
                        "amount_due": 20_000,
                        "currency": "usd",
                        "period_start": 1_779_120_000,
                        "period_end": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert ledger.invoices["ledger-in_555"].invoice_number == "ACAD-202605-001"


@pytest.mark.asyncio
async def test_invoice_paid_without_counters_leaves_invoice_number_none() -> None:
    """Backward compatible: callers that don't wire counters/settings still work,
    just without a minted invoice_number (None)."""
    enrollments = FakeBillingEnrollmentRepo()
    ledger = FakeLedgerRepo()
    enrollments.seed(
        StudentBillingEnrollment(
            enrollment_id="bill-1",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            session_type_id="type-elite",
            stripe_subscription_id="sub_123",
            billing_start_date=_now(),
            enrolled_at=_now(),
            updated_at=_now(),
        )
    )
    uc = _build(enrollments=enrollments, ledger=ledger)

    await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_paid_no_counters",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_556",
                        "subscription": "sub_123",
                        "payment_intent": "pi_556",
                        "amount_paid": 20_000,
                        "amount_due": 20_000,
                        "currency": "usd",
                        "period_start": 1_779_120_000,
                        "period_end": 1_781_712_000,
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert ledger.invoices["ledger-in_556"].invoice_number is None


@pytest.mark.asyncio
async def test_invoice_payment_failed_for_session_type_subscription_emits_invoice_failed() -> None:
    enrollments = FakeBillingEnrollmentRepo()
    ledger = FakeLedgerRepo()
    outbox = FakeOutbox()
    enrollments.seed(
        StudentBillingEnrollment(
            enrollment_id="bill-1",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            session_type_id="type-elite",
            stripe_subscription_id="sub_123",
            billing_start_date=_now(),
            enrolled_at=_now(),
            updated_at=_now(),
        )
    )
    uc = _build(enrollments=enrollments, ledger=ledger, outbox=outbox)

    await uc.execute(
        json.dumps(
            {
                "id": "evt_invoice_failed_session_type",
                "type": "invoice.payment_failed",
                "data": {
                    "object": {
                        "id": "in_124",
                        "subscription": "sub_123",
                        "amount_due": 20_000,
                        "currency": "usd",
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    assert ledger.invoices["ledger-in_124"].status == "open"
    assert [event.name for event in outbox.events] == ["Billing.InvoiceFailed"]


@pytest.mark.asyncio
async def test_subscription_deleted_cancels_student_billing_enrollment() -> None:
    enrollments = FakeBillingEnrollmentRepo()
    enrollments.seed(
        StudentBillingEnrollment(
            enrollment_id="bill-1",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            session_type_id="type-elite",
            stripe_subscription_id="sub_123",
            billing_start_date=_now(),
            enrolled_at=_now(),
            updated_at=_now(),
        )
    )
    uc = _build(enrollments=enrollments)

    await uc.execute(
        json.dumps(
            {
                "id": "evt_sub_deleted_session_type",
                "type": "customer.subscription.deleted",
                "data": {"object": {"id": "sub_123", "status": "canceled"}},
            }
        ).encode(),
        "test_signature",
    )

    assert enrollments.rows["bill-1"].status == "cancelled"
