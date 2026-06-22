"""Application tests for scheduled Stripe PaymentIntent reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.reconcile_stripe_payment_intents import (
    ReconcileStripePaymentIntents,
)
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerAllocationResult,
    LedgerInvoice,
    LedgerPayment,
    PaymentAllocation,
    allocate_payment_to_invoice,
)

_NOW = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)


@dataclass
class FakeStripeGateway:
    payment_intents: list[dict[str, Any]] = field(default_factory=list)
    searched: list[dict[str, Any]] = field(default_factory=list)

    async def search_app_owned_payment_intents(
        self, *, academy_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        self.searched.append({"academy_id": academy_id, "limit": limit})
        return self.payment_intents[:limit]


@dataclass
class FakeRunRecorder:
    runs: list[dict[str, Any]] = field(default_factory=list)

    async def record_run(self, **kwargs: Any) -> None:
        self.runs.append(kwargs)


@dataclass
class FakeLedger:
    invoices: dict[str, LedgerInvoice] = field(default_factory=dict)
    lines: dict[str, list[InvoiceLine]] = field(default_factory=dict)
    payments: dict[str, LedgerPayment] = field(default_factory=dict)
    allocations: dict[str, PaymentAllocation] = field(default_factory=dict)
    payment_idempotency: dict[str, str] = field(default_factory=dict)
    allocation_idempotency: dict[str, str] = field(default_factory=dict)

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self.invoices.get(invoice_id)

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

    async def get_payment_by_stripe_payment_intent_id(
        self, stripe_payment_intent_id: str
    ) -> LedgerPayment | None:
        return next(
            (
                payment
                for payment in self.payments.values()
                if payment.stripe_payment_intent_id == stripe_payment_intent_id
            ),
            None,
        )

    async def get_payment_allocation_by_idempotency_key(
        self, idempotency_key: str
    ) -> PaymentAllocation | None:
        allocation_id = self.allocation_idempotency.get(idempotency_key)
        return self.allocations.get(allocation_id or "")

    async def record_payment(
        self,
        payment: LedgerPayment,
        *,
        idempotency_key: str,
    ) -> LedgerPayment:
        existing_id = self.payment_idempotency.get(idempotency_key)
        if existing_id:
            return self.payments[existing_id]
        self.payments[payment.payment_id] = payment
        self.payment_idempotency[idempotency_key] = payment.payment_id
        return payment

    async def allocate_payment(
        self,
        *,
        payment_id: str,
        invoice_id: str,
        amount_cents: int,
        idempotency_key: str,
    ) -> LedgerAllocationResult:
        existing = await self.get_payment_allocation_by_idempotency_key(idempotency_key)
        if existing is not None:
            invoice = self.invoices[existing.invoice_id]
            payment = self.payments[existing.payment_id]
            return LedgerAllocationResult(
                invoice=invoice,
                payment=payment,
                allocation=existing,
                overpayment_credit=None,
            )

        invoice = self.invoices[invoice_id]
        payment = self.payments[payment_id]
        result = allocate_payment_to_invoice(
            invoice=invoice,
            payment=payment,
            lines=self.lines.get(invoice_id, []),
            requested_amount_cents=amount_cents,
            allocation_id=f"alloc-{len(self.allocations) + 1}",
            now=_NOW,
        )
        self.invoices[invoice_id] = result.invoice
        self.payments[payment_id] = result.payment
        self.allocations[result.allocation.allocation_id] = result.allocation
        self.allocation_idempotency[idempotency_key] = result.allocation.allocation_id
        return result


def _invoice(
    *,
    invoice_id: str = "inv-1",
    academy_id: str = "acad",
    parent_id: str = "parent-1",
    enrollment_id: str | None = "enr-1",
    period: str = "2026-06",
    total_cents: int = 5_000,
) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=academy_id,
        parent_id=parent_id,
        student_id="student-1",
        enrollment_id=enrollment_id,
        period=period,
        status="open",
        subtotal_cents=total_cents,
        discount_cents=0,
        total_cents=total_cents,
        balance_due_cents=total_cents,
        currency="usd",
        due_date=date(2026, 6, 30),
        source_type="monthly_tuition",
        source_id=enrollment_id,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _payment_intent(
    *,
    pi_id: str = "pi_reconcile_1",
    amount: int = 5_000,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "id": pi_id,
        "object": "payment_intent",
        "status": "succeeded",
        "amount": amount,
        "currency": "usd",
        "metadata": metadata
        or {
            "academy_id": "acad",
            "invoice_id": "inv-1",
            "parent_id": "parent-1",
            "source": "app_invoice_autopay",
        },
    }


@pytest.mark.asyncio
async def test_reconciler_repairs_paid_app_invoice_payment_intent() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    stripe = FakeStripeGateway(payment_intents=[_payment_intent()])
    recorder = FakeRunRecorder()
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=recorder,
        academy_id="acad",
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["scanned"] == 1
    assert result["repaired"] == 1
    assert ledger.invoices["inv-1"].status == "paid"
    assert ledger.invoices["inv-1"].balance_due_cents == 0
    assert [p.stripe_payment_intent_id for p in ledger.payments.values()] == ["pi_reconcile_1"]
    assert len(ledger.allocations) == 1
    assert recorder.runs[-1]["repaired"] == 1


@pytest.mark.asyncio
async def test_reconciler_rerun_is_idempotent() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    stripe = FakeStripeGateway(payment_intents=[_payment_intent()])
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=FakeRunRecorder(),
        academy_id="acad",
        clock=lambda: _NOW,
    )

    await uc.execute()
    await uc.execute()

    assert len(ledger.payments) == 1
    assert len(ledger.allocations) == 1
    assert ledger.invoices["inv-1"].status == "paid"


@pytest.mark.asyncio
async def test_reconciler_quarantines_duplicate_payment_intent_obligation() -> None:
    other_invoice = _invoice(invoice_id="inv-other")
    allocation = PaymentAllocation(
        allocation_id="alloc-existing",
        academy_id="acad",
        payment_id="pay-existing",
        invoice_id="inv-other",
        amount_cents=5_000,
        created_at=_NOW,
    )
    ledger = FakeLedger(
        invoices={"inv-1": _invoice(), "inv-other": other_invoice},
        payments={
            "pay-existing": LedgerPayment(
                payment_id="pay-existing",
                academy_id="acad",
                parent_id="parent-1",
                amount_cents=5_000,
                unapplied_amount_cents=0,
                currency="usd",
                status="succeeded",
                payment_method="stripe_autopay",
                stripe_payment_intent_id="pi_reconcile_1",
                paid_at=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        },
        allocations={"alloc-existing": allocation},
        payment_idempotency={"stripe-reconcile-pi:pi_reconcile_1": "pay-existing"},
        allocation_idempotency={"stripe-reconcile-alloc:pi_reconcile_1": "alloc-existing"},
    )
    stripe = FakeStripeGateway(payment_intents=[_payment_intent()])
    recorder = FakeRunRecorder()
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=recorder,
        academy_id="acad",
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["quarantined"] == 1
    assert result["repaired"] == 0
    assert ledger.invoices["inv-1"].status == "open"
    assert len(ledger.allocations) == 1
    assert recorder.runs[-1]["quarantined"] == 1


@pytest.mark.asyncio
async def test_reconciler_quarantines_cross_academy_payment_intent() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    stripe = FakeStripeGateway(
        payment_intents=[_payment_intent(metadata={"academy_id": "other", "invoice_id": "inv-1"})]
    )
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=FakeRunRecorder(),
        academy_id="acad",
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["quarantined"] == 1
    assert len(ledger.payments) == 0
    assert ledger.invoices["inv-1"].status == "open"


@pytest.mark.asyncio
async def test_reconciler_maps_legacy_subscription_invoice_to_app_created_invoice() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice(enrollment_id="enr-1", period="2026-06")})
    stripe = FakeStripeGateway(
        payment_intents=[
            _payment_intent(
                pi_id="pi_legacy_bridge",
                metadata={
                    "academy_id": "acad",
                    "parent_id": "parent-1",
                    "enrollment_id": "enr-1",
                    "period": "2026-06",
                    "stripe_invoice_id": "in_legacy_1",
                    "source": "stripe_subscription_invoice",
                },
            )
        ]
    )
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=FakeRunRecorder(),
        academy_id="acad",
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["repaired"] == 1
    assert ledger.invoices["inv-1"].status == "paid"
    assert [p.stripe_invoice_id for p in ledger.payments.values()] == ["in_legacy_1"]
