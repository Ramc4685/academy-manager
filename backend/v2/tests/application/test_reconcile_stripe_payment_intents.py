"""Application tests for scheduled Stripe PaymentIntent reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.reconcile_stripe_payment_intents import (
    ReconcileStripePaymentIntents,
)
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
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
    # stripe_account -> extra PIs only visible when searching that connected account
    connected_payment_intents: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    searched: list[dict[str, Any]] = field(default_factory=list)

    async def search_app_owned_payment_intents(
        self, *, academy_id: str, limit: int = 100, stripe_account: str | None = None
    ) -> list[dict[str, Any]]:
        self.searched.append(
            {"academy_id": academy_id, "limit": limit, "stripe_account": stripe_account}
        )
        if stripe_account is not None:
            return self.connected_payment_intents.get(stripe_account, [])[:limit]
        return self.payment_intents[:limit]


class FailingStripeGateway(FakeStripeGateway):
    async def search_app_owned_payment_intents(
        self, *, academy_id: str, limit: int = 100, stripe_account: str | None = None
    ) -> list[dict[str, Any]]:
        raise RuntimeError("stripe search unavailable")


@dataclass
class FakeConnectedAccounts:
    account: ConnectedAccount | None = None
    calls: int = 0

    async def get_for_academy(self) -> ConnectedAccount | None:
        self.calls += 1
        return self.account


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
    status: str = "succeeded",
    payment_method_types: list[str] | None = None,
    created: datetime | None = None,
) -> dict[str, Any]:
    pi: dict[str, Any] = {
        "id": pi_id,
        "object": "payment_intent",
        "status": status,
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
    if payment_method_types is not None:
        pi["payment_method_types"] = payment_method_types
    if created is not None:
        pi["created"] = int(created.timestamp())
    return pi


def _ach_processing_pi(
    *,
    pi_id: str = "pi_ach_processing",
    amount: int = 5_000,
    metadata: dict[str, str] | None = None,
    created: datetime | None = None,
) -> dict[str, Any]:
    return _payment_intent(
        pi_id=pi_id,
        amount=amount,
        metadata=metadata,
        status="processing",
        payment_method_types=["us_bank_account"],
        created=created or _NOW,
    )


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
async def test_reconciler_records_note_when_stripe_search_scans_zero() -> None:
    recorder = FakeRunRecorder()
    uc = ReconcileStripePaymentIntents(
        stripe=FakeStripeGateway(payment_intents=[]),
        ledger=FakeLedger(),
        run_recorder=recorder,
        academy_id="acad",
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["scanned"] == 0
    assert result["notes"] == [
        "Stripe returned no app-owned PaymentIntents. Checkout payments created before "
        "PaymentIntent metadata was deployed require manual review by Stripe id."
    ]
    assert recorder.runs[-1]["notes"] == result["notes"]


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


@pytest.mark.asyncio
async def test_reconciler_repairs_balance_payment_intent_across_invoice_ids() -> None:
    ledger = FakeLedger(
        invoices={
            "inv-1": _invoice(invoice_id="inv-1", parent_id="parent-1", total_cents=4_000),
            "inv-2": _invoice(invoice_id="inv-2", parent_id="parent-1", total_cents=6_000),
        }
    )
    stripe = FakeStripeGateway(
        payment_intents=[
            _payment_intent(
                pi_id="pi_balance_reconcile",
                amount=10_000,
                metadata={
                    "academy_id": "acad",
                    "parent_id": "parent-1",
                    "invoice_ids": "inv-1,inv-2",
                    "type": "balance_payment",
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

    assert result["scanned"] == 1
    assert result["repaired"] == 1
    assert ledger.invoices["inv-1"].status == "paid"
    assert ledger.invoices["inv-1"].balance_due_cents == 0
    assert ledger.invoices["inv-2"].status == "paid"
    assert ledger.invoices["inv-2"].balance_due_cents == 0
    assert [p.stripe_payment_intent_id for p in ledger.payments.values()] == [
        "pi_balance_reconcile"
    ]
    assert {a.invoice_id: a.amount_cents for a in ledger.allocations.values()} == {
        "inv-1": 4_000,
        "inv-2": 6_000,
    }


@pytest.mark.asyncio
async def test_reconciler_balance_payment_intent_rerun_is_idempotent() -> None:
    ledger = FakeLedger(
        invoices={
            "inv-1": _invoice(invoice_id="inv-1", parent_id="parent-1", total_cents=4_000),
            "inv-2": _invoice(invoice_id="inv-2", parent_id="parent-1", total_cents=6_000),
        }
    )
    stripe = FakeStripeGateway(
        payment_intents=[
            _payment_intent(
                pi_id="pi_balance_reconcile",
                amount=10_000,
                metadata={
                    "academy_id": "acad",
                    "parent_id": "parent-1",
                    "invoice_ids": "inv-1,inv-2",
                    "type": "balance_payment",
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

    first = await uc.execute()
    second = await uc.execute()

    assert first["repaired"] == 1
    assert second["repaired"] == 0
    assert second["skipped"] == 1
    assert len(ledger.payments) == 1
    assert len(ledger.allocations) == 2
    assert ledger.invoices["inv-1"].status == "paid"
    assert ledger.invoices["inv-2"].status == "paid"


def _paid_invoice(
    *, invoice_id: str = "inv-1", parent_id: str = "parent-1", total_cents: int = 5_000
) -> LedgerInvoice:
    return _invoice(invoice_id=invoice_id, parent_id=parent_id, total_cents=total_cents).model_copy(
        update={"status": "paid", "balance_due_cents": 0}
    )


def _webhook_payment(
    *, pi_id: str, payment_id: str, parent_id: str = "parent-1", amount: int = 5_000
) -> LedgerPayment:
    """A ledger payment as a Checkout webhook would have recorded it."""
    return LedgerPayment(
        payment_id=payment_id,
        academy_id="acad",
        parent_id=parent_id,
        amount_cents=amount,
        unapplied_amount_cents=0,
        currency="usd",
        status="succeeded",
        payment_method="stripe_checkout",
        stripe_payment_intent_id=pi_id,
        paid_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.asyncio
async def test_reconciler_skips_single_invoice_already_recorded_by_webhook() -> None:
    """Webhook already closed the invoice; reconciler must not duplicate the payment."""
    ledger = FakeLedger(
        invoices={"inv-1": _paid_invoice()},
        payments={
            "ledger-pay-cs:cs_1": _webhook_payment(
                pi_id="pi_reconcile_1", payment_id="ledger-pay-cs:cs_1"
            )
        },
    )
    stripe = FakeStripeGateway(payment_intents=[_payment_intent()])
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=FakeRunRecorder(),
        academy_id="acad",
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["scanned"] == 1
    assert result["repaired"] == 0
    assert result["skipped"] == 1
    assert len(ledger.payments) == 1  # no duplicate phantom payment
    assert ledger.invoices["inv-1"].balance_due_cents == 0


@pytest.mark.asyncio
async def test_reconciler_skips_balance_payment_already_recorded_by_webhook() -> None:
    """Webhook already closed the balance batch; reconciler must not duplicate the payment."""
    ledger = FakeLedger(
        invoices={
            "inv-1": _paid_invoice(invoice_id="inv-1", total_cents=4_000),
            "inv-2": _paid_invoice(invoice_id="inv-2", total_cents=6_000),
        },
        payments={
            "ledger-pay-cs:cs_2": _webhook_payment(
                pi_id="pi_balance_1", payment_id="ledger-pay-cs:cs_2", amount=10_000
            )
        },
    )
    stripe = FakeStripeGateway(
        payment_intents=[
            _payment_intent(
                pi_id="pi_balance_1",
                amount=10_000,
                metadata={
                    "academy_id": "acad",
                    "parent_id": "parent-1",
                    "invoice_ids": "inv-1,inv-2",
                    "type": "balance_payment",
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

    assert result["repaired"] == 0
    assert result["skipped"] == 1
    assert len(ledger.payments) == 1  # no duplicate phantom payment


# ---------------------------------------------------------------------------
# ACH-aware reconciliation (checklist item #16, §7.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciler_counts_ach_processing_pi_separately_not_as_error() -> None:
    """An in-flight ACH debit (status=processing) is a known, non-erroring state.

    It must not be counted as failed/quarantined/mismatched, and must not create
    a ledger payment (settlement hasn't happened yet) — but it must be visible
    in a dedicated bucket so reconciliation isn't silently blind to it.
    """
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    stripe = FakeStripeGateway(payment_intents=[_ach_processing_pi()])
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
    assert result["ach_processing_count"] == 1
    assert result["failed"] == 0
    assert result["quarantined"] == 0
    assert result["repaired"] == 0
    # Not treated as a generic skip either — it's distinguishable.
    assert result["skipped"] == 0
    assert len(ledger.payments) == 0
    assert ledger.invoices["inv-1"].status == "open"
    assert recorder.runs[-1]["ach_processing_count"] == 1


@pytest.mark.asyncio
async def test_reconciler_flags_stale_ach_processing_for_human_review() -> None:
    """An ACH PI stuck in `processing` well past normal settlement (5 business
    days) is still not a hard error, but must be surfaced for a human to look
    at — mirroring the existing 'notes'-style soft-surface pattern rather than
    silently swallowing a legitimately stuck payment."""
    stale_created = _NOW - timedelta(days=10)
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    stripe = FakeStripeGateway(
        payment_intents=[_ach_processing_pi(pi_id="pi_ach_stale", created=stale_created)]
    )
    recorder = FakeRunRecorder()
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=recorder,
        academy_id="acad",
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["ach_processing_count"] == 1
    assert result["failed"] == 0
    assert result["quarantined"] == 0
    assert len(result["stale_ach_processing"]) == 1
    assert result["stale_ach_processing"][0]["payment_intent_id"] == "pi_ach_stale"
    assert recorder.runs[-1]["stale_ach_processing"] == result["stale_ach_processing"]


@pytest.mark.asyncio
async def test_reconciler_recent_ach_processing_is_not_flagged_stale() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    stripe = FakeStripeGateway(payment_intents=[_ach_processing_pi(created=_NOW)])
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=FakeRunRecorder(),
        academy_id="acad",
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["ach_processing_count"] == 1
    assert result["stale_ach_processing"] == []


@pytest.mark.asyncio
async def test_reconciler_records_and_returns_when_search_fails() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    recorder = FakeRunRecorder()
    uc = ReconcileStripePaymentIntents(
        stripe=FailingStripeGateway(),
        ledger=ledger,
        run_recorder=recorder,
        academy_id="acad",
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["scanned"] == 0
    assert result["failed"] == 1
    assert result["finished_at"] == _NOW
    assert result["errors"] == ["PaymentIntent search failed: stripe search unavailable"]
    assert recorder.runs[-1] == result


@pytest.mark.asyncio
async def test_reconciler_searches_platform_only_when_no_connected_account() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    stripe = FakeStripeGateway(payment_intents=[_payment_intent()])
    connected_accounts = FakeConnectedAccounts(account=None)
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=FakeRunRecorder(),
        academy_id="acad",
        connected_accounts=connected_accounts,
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["repaired"] == 1
    assert connected_accounts.calls == 1
    assert len(stripe.searched) == 1
    assert stripe.searched[0]["stripe_account"] is None


@pytest.mark.asyncio
async def test_reconciler_searches_per_connected_account_with_stripe_account_scoping() -> None:
    """Slice I: money routed through a connected account must not be invisible
    to reconciliation. The gateway must be called once for platform-level PIs
    and once more scoped to the academy's connected Stripe account."""
    ledger = FakeLedger(
        invoices={
            "inv-1": _invoice(invoice_id="inv-1"),
            "inv-2": _invoice(invoice_id="inv-2", enrollment_id="enr-2"),
        }
    )
    connected_pi = _payment_intent(
        pi_id="pi_connected_1",
        metadata={
            "academy_id": "acad",
            "invoice_id": "inv-2",
            "parent_id": "parent-1",
            "source": "app_invoice_autopay",
        },
    )
    stripe = FakeStripeGateway(
        payment_intents=[_payment_intent(pi_id="pi_platform_1")],
        connected_payment_intents={"acct_connected_acad": [connected_pi]},
    )
    connected_accounts = FakeConnectedAccounts(
        account=ConnectedAccount.new(academy_id="acad", stripe_account_id="acct_connected_acad")
    )
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=FakeRunRecorder(),
        academy_id="acad",
        connected_accounts=connected_accounts,
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["scanned"] == 2
    assert result["repaired"] == 2
    assert ledger.invoices["inv-1"].status == "paid"
    assert ledger.invoices["inv-2"].status == "paid"
    assert len(stripe.searched) == 2
    stripe_account_args = {call["stripe_account"] for call in stripe.searched}
    assert stripe_account_args == {None, "acct_connected_acad"}


@pytest.mark.asyncio
async def test_reconciler_tenant_isolation_across_connected_accounts() -> None:
    """One academy's connected-account PIs must attribute to that academy only;
    a differently-scoped academy_id in metadata on a connected-account PI must
    still be quarantined, never silently attributed cross-tenant."""
    ledger = FakeLedger(invoices={"inv-1": _invoice(academy_id="acad")})
    mismatched_pi = _payment_intent(
        pi_id="pi_wrong_academy",
        metadata={
            "academy_id": "other-academy",
            "invoice_id": "inv-1",
            "parent_id": "parent-1",
        },
    )
    stripe = FakeStripeGateway(
        payment_intents=[],
        connected_payment_intents={"acct_connected_acad": [mismatched_pi]},
    )
    connected_accounts = FakeConnectedAccounts(
        account=ConnectedAccount.new(academy_id="acad", stripe_account_id="acct_connected_acad")
    )
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=FakeRunRecorder(),
        academy_id="acad",
        connected_accounts=connected_accounts,
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["quarantined"] == 1
    assert len(ledger.payments) == 0
    assert ledger.invoices["inv-1"].status == "open"


@pytest.mark.asyncio
async def test_reconciler_dedupes_pi_seen_in_both_platform_and_connected_search() -> None:
    """If the same PI id shows up in both searches (shouldn't normally happen,
    but defensively), it must only be reconciled once."""
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    pi = _payment_intent(pi_id="pi_dupe")
    stripe = FakeStripeGateway(
        payment_intents=[pi],
        connected_payment_intents={"acct_connected_acad": [pi]},
    )
    connected_accounts = FakeConnectedAccounts(
        account=ConnectedAccount.new(academy_id="acad", stripe_account_id="acct_connected_acad")
    )
    uc = ReconcileStripePaymentIntents(
        stripe=stripe,
        ledger=ledger,
        run_recorder=FakeRunRecorder(),
        academy_id="acad",
        connected_accounts=connected_accounts,
        clock=lambda: _NOW,
    )

    result = await uc.execute()

    assert result["scanned"] == 1
    assert result["repaired"] == 1
    assert len(ledger.payments) == 1
