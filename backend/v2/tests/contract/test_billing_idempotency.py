from __future__ import annotations

import asyncio
import importlib
import json
from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerInvoice,
    LedgerPayment,
)
from backend.v2.contexts.billing.domain.models import Subscription
from backend.v2.contexts.billing.domain.session_type import StudentBillingEnrollment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.application.test_webhook_handler import (
    FakeDedup,
    FakeOutbox,
    FakePaymentRepo,
    FakeSubscriptionRepo,
)


@pytest.mark.asyncio
async def test_invoice_creation_is_idempotent_per_tenant(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    invoice = LedgerInvoice(
        invoice_id="inv-idempotent",
        academy_id=acad,
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enroll-1",
        period="2026-06",
        status="open",
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=10_000,
        currency="usd",
        due_date=date(2026, 6, 10),
        created_at=now,
        updated_at=now,
    )
    lines = [
        InvoiceLine(
            line_id="line-idempotent",
            academy_id=acad,
            invoice_id="inv-idempotent",
            line_type="tuition",
            description="June tuition",
            quantity=1,
            unit_amount_cents=10_000,
            amount_cents=10_000,
            source_type="enrollment",
            source_id="enroll-1",
            created_at=now,
        )
    ]

    first = await repo.create_invoice(
        invoice,
        lines=lines,
        idempotency_key="invoice:enroll-1:2026-06",
    )
    second = await repo.create_invoice(
        invoice,
        lines=lines,
        idempotency_key="invoice:enroll-1:2026-06",
    )

    assert first == second
    assert await db["invoices"].count_documents({"academy_id": acad}) == 1
    assert await db["invoice_lines"].count_documents({"academy_id": acad}) == 1


@pytest.mark.asyncio
async def test_allocation_overpayment_credit_is_idempotent(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        LedgerInvoice(
            invoice_id="inv-overpay",
            academy_id=acad,
            parent_id="parent-1",
            period="2026-06",
            status="open",
            subtotal_cents=10_000,
            discount_cents=0,
            total_cents=10_000,
            balance_due_cents=10_000,
            currency="usd",
            due_date=date(2026, 6, 10),
            created_at=now,
            updated_at=now,
        ),
        lines=[],
        idempotency_key="invoice:overpay",
    )
    await repo.record_payment(
        LedgerPayment(
            payment_id="pay-overpay",
            academy_id=acad,
            parent_id="parent-1",
            amount_cents=12_000,
            unapplied_amount_cents=12_000,
            currency="usd",
            status="succeeded",
            payment_method="cash",
            paid_at=now,
            created_at=now,
            updated_at=now,
        ),
        idempotency_key="payment:manual:receipt-1",
    )

    first = await repo.allocate_payment(
        payment_id="pay-overpay",
        invoice_id="inv-overpay",
        amount_cents=12_000,
        idempotency_key="allocation:receipt-1:inv-overpay",
    )
    second = await repo.allocate_payment(
        payment_id="pay-overpay",
        invoice_id="inv-overpay",
        amount_cents=12_000,
        idempotency_key="allocation:receipt-1:inv-overpay",
    )

    assert first == second
    invoice = await db["invoices"].find_one({"academy_id": acad, "invoice_id": "inv-overpay"})
    payment = await db["ledger_payments"].find_one(
        {"academy_id": acad, "payment_id": "pay-overpay"}
    )
    assert invoice is not None
    assert payment is not None
    assert (
        await db["payments"].count_documents({"academy_id": acad, "payment_id": "pay-overpay"}) == 0
    )
    assert invoice["balance_due_cents"] == 0
    assert invoice["status"] == "paid"
    assert payment["unapplied_amount_cents"] == 0
    assert await db["payment_allocations"].count_documents({"academy_id": acad}) == 1
    credits = [doc async for doc in db["account_credit_ledger"].find({"academy_id": acad})]
    assert len(credits) == 1
    assert credits[0]["type"] == "MANUAL_CREDIT"
    assert credits[0]["source_type"] == "OVERPAYMENT"
    assert credits[0]["source_id"] == first.allocation.allocation_id
    assert credits[0]["amount_cents"] == 2_000
    assert credits[0]["remaining_amount_cents"] == 2_000


@pytest.mark.asyncio
async def test_allocation_replay_repairs_invoice_and_payment_projection(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        LedgerInvoice(
            invoice_id="inv-partial-write",
            academy_id=acad,
            parent_id="parent-1",
            period="2026-06",
            status="open",
            subtotal_cents=7_000,
            discount_cents=0,
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            due_date=date(2026, 6, 10),
            created_at=now,
            updated_at=now,
        ),
        lines=[],
        idempotency_key="invoice:partial-write",
    )
    await repo.record_payment(
        LedgerPayment(
            payment_id="pay-partial-write",
            academy_id=acad,
            parent_id="parent-1",
            amount_cents=7_000,
            unapplied_amount_cents=7_000,
            currency="usd",
            status="succeeded",
            payment_method="stripe",
            stripe_payment_intent_id="pi_partial_write",
            paid_at=now,
            created_at=now,
            updated_at=now,
        ),
        idempotency_key="payment:partial-write",
    )
    await db["payment_allocations"].insert_one(
        {
            "allocation_id": "alloc-partial-write",
            "academy_id": acad,
            "payment_id": "pay-partial-write",
            "invoice_id": "inv-partial-write",
            "amount_cents": 7_000,
            "created_at": now,
            "idempotency_key": "allocation:partial-write",
        }
    )

    result = await repo.allocate_payment(
        payment_id="pay-partial-write",
        invoice_id="inv-partial-write",
        amount_cents=7_000,
        idempotency_key="allocation:partial-write",
    )

    assert result.invoice.status == "paid"
    assert result.invoice.balance_due_cents == 0
    assert result.payment.unapplied_amount_cents == 0
    invoice = await db["invoices"].find_one({"academy_id": acad, "invoice_id": "inv-partial-write"})
    payment = await db["ledger_payments"].find_one(
        {"academy_id": acad, "payment_id": "pay-partial-write"}
    )
    assert invoice is not None
    assert payment is not None
    assert invoice["status"] == "paid"
    assert invoice["balance_due_cents"] == 0
    assert payment["unapplied_amount_cents"] == 0
    assert (
        await db["payment_allocations"].count_documents(
            {"academy_id": acad, "idempotency_key": "allocation:partial-write"}
        )
        == 1
    )


@pytest.mark.asyncio
async def test_concurrent_allocations_cannot_double_pay_invoice(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        LedgerInvoice(
            invoice_id="inv-concurrent",
            academy_id=acad,
            parent_id="parent-1",
            period="2026-06",
            status="open",
            subtotal_cents=7_000,
            discount_cents=0,
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            due_date=date(2026, 6, 10),
            created_at=now,
            updated_at=now,
        ),
        lines=[],
        idempotency_key="invoice:concurrent",
    )
    for payment_id in ("pay-concurrent-a", "pay-concurrent-b"):
        await repo.record_payment(
            LedgerPayment(
                payment_id=payment_id,
                academy_id=acad,
                parent_id="parent-1",
                amount_cents=7_000,
                unapplied_amount_cents=7_000,
                currency="usd",
                status="succeeded",
                payment_method="stripe",
                paid_at=now,
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=f"payment:{payment_id}",
        )

    class DelayedInvoiceUpdate:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self.calls = 0

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        async def update_one(self, filter_, update, *args, **kwargs):
            set_fields = update.get("$set", {}) if isinstance(update, dict) else {}
            if filter_.get("invoice_id") == "inv-concurrent" and "balance_due_cents" in set_fields:
                self.calls += 1
                if self.calls == 1:
                    for _ in range(100):
                        count = await db["payment_allocations"].count_documents(
                            {"academy_id": acad, "invoice_id": "inv-concurrent"}
                        )
                        if count >= 2:
                            break
                        await asyncio.sleep(0)
            return await self._wrapped.update_one(filter_, update, *args, **kwargs)

    repo.collection = DelayedInvoiceUpdate(repo.collection)

    async def allocate(payment_id: str, key: str):
        try:
            return await repo.allocate_payment(
                payment_id=payment_id,
                invoice_id="inv-concurrent",
                amount_cents=7_000,
                idempotency_key=key,
            )
        except ValueError as exc:
            return exc

    results = await asyncio.gather(
        allocate("pay-concurrent-a", "allocation:concurrent:a"),
        allocate("pay-concurrent-b", "allocation:concurrent:b"),
    )

    invoice = await db["invoices"].find_one({"academy_id": acad, "invoice_id": "inv-concurrent"})
    assert invoice is not None
    assert invoice["status"] == "paid"
    assert invoice["balance_due_cents"] == 0
    assert (
        await db["payment_allocations"].count_documents(
            {"academy_id": acad, "invoice_id": "inv-concurrent"}
        )
        == 1
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1


@pytest.mark.asyncio
async def test_ledger_payment_allocation_uses_ledger_collection_with_legacy_index(db, acad) -> None:
    await db["payments"].create_index(
        [("enrollment_id", 1), ("period", 1)],
        unique=True,
        name="enrollment_id_1_period_1",
    )
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "legacy-null-period",
            "parent_id": "parent-legacy",
            "amount_cents": 1_000,
            "status": "pending",
            "enrollment_id": None,
            "period": None,
        }
    )

    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        LedgerInvoice(
            invoice_id="inv-stripe-paid",
            academy_id=acad,
            parent_id="parent-1",
            period="2026-06",
            status="open",
            subtotal_cents=10_000,
            discount_cents=0,
            total_cents=10_000,
            balance_due_cents=10_000,
            currency="usd",
            due_date=date(2026, 6, 10),
            created_at=now,
            updated_at=now,
        ),
        lines=[],
        idempotency_key="invoice:stripe-paid",
    )

    payment = await repo.record_payment(
        LedgerPayment(
            payment_id="ledger-pay-in-1",
            academy_id=acad,
            parent_id="parent-1",
            amount_cents=10_000,
            unapplied_amount_cents=10_000,
            currency="usd",
            status="succeeded",
            payment_method="stripe",
            stripe_payment_intent_id="pi_invoice_1",
            paid_at=now,
            created_at=now,
            updated_at=now,
        ),
        idempotency_key="stripe-invoice-payment:in_1",
    )
    allocation = await repo.allocate_payment(
        payment_id=payment.payment_id,
        invoice_id="inv-stripe-paid",
        amount_cents=10_000,
        idempotency_key="stripe-invoice-allocation:in_1",
    )

    assert allocation.invoice.status == "paid"
    assert await db["payments"].count_documents({"academy_id": acad}) == 1
    assert await db["ledger_payments"].count_documents({"academy_id": acad}) == 1
    assert await db["payment_allocations"].count_documents({"academy_id": acad}) == 1


@pytest.mark.asyncio
async def test_invoice_paid_session_type_webhook_allocates_with_legacy_payment_index(
    db, acad
) -> None:
    await db["payments"].create_index(
        [("enrollment_id", 1), ("period", 1)],
        unique=True,
        name="enrollment_id_1_period_1",
    )
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "legacy-null-period",
            "parent_id": "parent-legacy",
            "amount_cents": 1_000,
            "status": "pending",
            "enrollment_id": None,
            "period": None,
        }
    )

    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    enrollments = MongoStudentBillingEnrollmentRepository(db)
    await enrollments.save(
        StudentBillingEnrollment(
            enrollment_id="bill-1",
            academy_id=acad,
            student_id="student-1",
            parent_id="parent-1",
            session_type_id="type-elite",
            stripe_subscription_id="sub_123",
            billing_start_date=now,
            enrolled_at=now,
            updated_at=now,
        )
    )
    outbox = FakeOutbox()
    use_case = HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        billing_enrollments=enrollments,
        billing_ledger=MongoBillingLedgerRepository(db, clock=lambda: now),
        outbox=outbox,
        academy_id=acad,
        clock=lambda: now,
    )

    await use_case.execute(
        json.dumps(
            {
                "id": "evt_invoice_paid_legacy_index",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_legacy_index",
                        "subscription": "sub_123",
                        "payment_intent": "pi_legacy_index",
                        "amount_paid": 20_000,
                        "amount_due": 20_000,
                        "currency": "usd",
                    }
                },
            }
        ).encode(),
        "test_signature",
    )

    invoice = await db["invoices"].find_one(
        {"academy_id": acad, "invoice_id": "ledger-in_legacy_index"}
    )
    ledger_payment = await db["ledger_payments"].find_one(
        {"academy_id": acad, "payment_id": "ledger-pay-in_legacy_index"}
    )
    assert invoice is not None
    assert invoice["status"] == "paid"
    assert invoice["balance_due_cents"] == 0
    assert ledger_payment is not None
    assert ledger_payment["stripe_payment_intent_id"] == "pi_legacy_index"
    assert ledger_payment["unapplied_amount_cents"] == 0
    assert await db["payments"].count_documents({"academy_id": acad}) == 1
    assert await db["payment_allocations"].count_documents({"academy_id": acad}) == 1
    assert [event.name for event in outbox.events] == ["Billing.InvoicePaid"]


@pytest.mark.asyncio
async def test_subscription_invoice_paid_allocates_existing_ledger_invoice_idempotently(
    db, acad
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    ledger = MongoBillingLedgerRepository(db, clock=lambda: now)
    await ledger.create_invoice(
        LedgerInvoice(
            invoice_id="inv-monthly-enr-1-2026-06",
            academy_id=acad,
            parent_id="parent-1",
            student_id="student-1",
            enrollment_id="enr-1",
            period="2026-06",
            status="open",
            subtotal_cents=7_000,
            discount_cents=0,
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            due_date=date(2026, 6, 10),
            created_at=now,
            updated_at=now,
        ),
        lines=[
            InvoiceLine(
                line_id="line-monthly-enr-1-2026-06",
                academy_id=acad,
                invoice_id="inv-monthly-enr-1-2026-06",
                line_type="tuition",
                description="June tuition",
                quantity=1,
                unit_amount_cents=7_000,
                amount_cents=7_000,
                source_type="enrollment",
                source_id="enr-1",
                created_at=now,
            )
        ],
        idempotency_key="monthly-ledger-enr-1-2026-06",
    )

    subscriptions = FakeSubscriptionRepo()
    subscriptions.seed(
        Subscription(
            subscription_id="sub-local-1",
            academy_id=acad,
            parent_id="parent-1",
            enrollment_id="enr-1",
            session_id="session-1",
            stripe_subscription_id="sub_stripe_1",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    payments = FakePaymentRepo()
    use_case = HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=payments,
        subscriptions=subscriptions,
        billing_ledger=ledger,
        outbox=FakeOutbox(),
        academy_id=acad,
        clock=lambda: now,
    )
    invoice_object = {
        "id": "in_subscription_1",
        "parent": {"subscription_details": {"subscription": "sub_stripe_1"}},
        "payment_intent": None,
        "amount_paid": 7_000,
        "amount_due": 7_000,
        "currency": "usd",
        "period_start": 1_781_712_000,
    }

    for event_id in ("evt_subscription_paid_1", "evt_subscription_paid_2"):
        await use_case.execute(
            json.dumps(
                {
                    "id": event_id,
                    "type": "invoice.paid",
                    "data": {"object": invoice_object},
                }
            ).encode(),
            "test_signature",
        )

    invoice = await db["invoices"].find_one(
        {"academy_id": acad, "invoice_id": "inv-monthly-enr-1-2026-06"}
    )
    payment = await db["ledger_payments"].find_one(
        {"academy_id": acad, "payment_id": "ledger-pay-in_subscription_1"}
    )
    assert invoice is not None
    assert invoice["status"] == "paid"
    assert invoice["balance_due_cents"] == 0
    assert invoice["stripe_invoice_id"] == "in_subscription_1"
    assert payment is not None
    assert payment["stripe_payment_intent_id"] == "in_subscription_1"
    assert payment["stripe_invoice_id"] == "in_subscription_1"
    assert payment["unapplied_amount_cents"] == 0
    assert await db["ledger_payments"].count_documents({"academy_id": acad}) == 1
    assert await db["payment_allocations"].count_documents({"academy_id": acad}) == 1
    assert len(payments.by_id) == 1


@pytest.mark.asyncio
async def test_billing_ledger_reads_are_tenant_isolated(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        LedgerInvoice(
            invoice_id="inv-tenant",
            academy_id=acad,
            parent_id="parent-1",
            period="2026-06",
            status="open",
            subtotal_cents=5_000,
            discount_cents=0,
            total_cents=5_000,
            balance_due_cents=5_000,
            currency="usd",
            due_date=date(2026, 6, 10),
            created_at=now,
            updated_at=now,
        ),
        lines=[],
        idempotency_key="invoice:tenant",
    )

    assert await repo.get_invoice("inv-tenant") is not None
    with tenant_scope("other-academy"):
        other_repo = MongoBillingLedgerRepository(db)
        assert await other_repo.get_invoice("inv-tenant") is None


@pytest.mark.asyncio
async def test_ledger_payment_storage_ignores_legacy_payments_collection(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        LedgerInvoice(
            invoice_id="inv-storage-split",
            academy_id=acad,
            parent_id="parent-1",
            period="2026-06",
            status="open",
            subtotal_cents=5_000,
            discount_cents=0,
            total_cents=5_000,
            balance_due_cents=5_000,
            currency="usd",
            due_date=date(2026, 6, 10),
            created_at=now,
            updated_at=now,
        ),
        lines=[],
        idempotency_key="invoice:storage-split",
    )
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-storage-split",
            "parent_id": "parent-1",
            "amount_cents": 5_000,
            "status": "succeeded",
            "ledger_idempotency_key": "payment:storage-split",
            "created_at": now,
            "updated_at": now,
        }
    )

    with pytest.raises(ValueError, match="payment not found"):
        await repo.allocate_payment(
            payment_id="pay-storage-split",
            invoice_id="inv-storage-split",
            amount_cents=5_000,
            idempotency_key="allocation:storage-split",
        )

    await repo.record_payment(
        LedgerPayment(
            payment_id="pay-storage-split",
            academy_id=acad,
            parent_id="parent-1",
            amount_cents=5_000,
            unapplied_amount_cents=5_000,
            currency="usd",
            status="succeeded",
            payment_method="cash",
            paid_at=now,
            created_at=now,
            updated_at=now,
        ),
        idempotency_key="payment:storage-split",
    )

    result = await repo.allocate_payment(
        payment_id="pay-storage-split",
        invoice_id="inv-storage-split",
        amount_cents=5_000,
        idempotency_key="allocation:storage-split",
    )

    assert result.invoice.status == "paid"
    assert (
        await db["ledger_payments"].count_documents(
            {"academy_id": acad, "payment_id": "pay-storage-split"}
        )
        == 1
    )


@pytest.mark.asyncio
async def test_ledger_payments_migration_copies_only_ledger_shape_without_deleting(
    db, acad
) -> None:
    migration = importlib.import_module("backend.v2.migrations.0128_ledger_payments_storage")
    audit_script = importlib.import_module("backend.scripts.ledger_payments_storage_audit")
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["payments"].insert_many(
        [
            {
                "academy_id": acad,
                "payment_id": "pay-ledger-copy",
                "parent_id": "parent-1",
                "amount_cents": 5_000,
                "unapplied_amount_cents": 5_000,
                "ledger_idempotency_key": "payment:ledger-copy",
                "status": "succeeded",
                "created_at": now,
                "updated_at": now,
            },
            {
                "academy_id": acad,
                "payment_id": "pay-legacy-keep",
                "parent_id": "parent-1",
                "enrollment_id": "enroll-1",
                "amount_cents": 6_000,
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            },
        ]
    )

    before = await audit_script.audit(db)
    assert before == {
        "legacy_ledger_shaped_payments": 1,
        "ledger_payments": 0,
        "missing_from_ledger_payments": 1,
    }

    await migration.up(db)
    await migration.up(db)

    after = await audit_script.audit(db)
    assert after == {
        "legacy_ledger_shaped_payments": 1,
        "ledger_payments": 1,
        "missing_from_ledger_payments": 0,
    }

    copied = await db["ledger_payments"].find_one(
        {"academy_id": acad, "payment_id": "pay-ledger-copy"}
    )
    assert copied is not None
    assert copied["ledger_idempotency_key"] == "payment:ledger-copy"
    assert await db["ledger_payments"].count_documents({"academy_id": acad}) == 1
    assert await db["payments"].count_documents({"academy_id": acad}) == 2
    assert await db["payments"].find_one({"academy_id": acad, "payment_id": "pay-legacy-keep"})
