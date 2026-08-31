"""Regression tests for #518: one payment's funds can only be spent once.

``MongoBillingLedgerRepository.allocate_payment`` used to CAS-guard only the
invoice-side write; the payment's ``unapplied_amount_cents`` was written with an
unconditional ``$set`` computed from the snapshot read at the top of the method.
Two allocators racing on the same payment under different idempotency keys (the
webhook worker vs. an admin legacy match vs. the reconciler) therefore both
passed the domain funds check and both marked their invoice paid with the same
money — and the repair paths floored the resulting negative unapplied balance to
0, hiding the over-allocation.

These tests interleave the two writers at the exact mid-race point (the loser's
snapshot is handed out *after* the winner has already committed) rather than
asserting a validation error on a serial second call.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, LedgerPayment
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)

NOW = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)


def _invoice(invoice_id: str, academy_id: str, amount: int = 10_000) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=academy_id,
        parent_id="parent-518",
        period="2026-06",
        status="open",
        subtotal_cents=amount,
        discount_cents=0,
        total_cents=amount,
        balance_due_cents=amount,
        currency="usd",
        due_date=date(2026, 6, 30),
        created_at=NOW,
        updated_at=NOW,
    )


def _payment(payment_id: str, academy_id: str, amount: int = 10_000) -> LedgerPayment:
    return LedgerPayment(
        payment_id=payment_id,
        academy_id=academy_id,
        parent_id="parent-518",
        amount_cents=amount,
        unapplied_amount_cents=amount,
        currency="usd",
        status="succeeded",
        payment_method="cash",
        paid_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


class _RacingPaymentsCollection:
    """Wraps ``ledger_payments`` and runs a competing writer mid-read.

    The hook fires once, right after the racing repository has read the payment
    snapshot it will compute its allocation from. The competing allocator then
    runs to completion, so the snapshot the caller receives is already stale by
    the time it is used — the exact interleaving that #518 describes.
    """

    def __init__(self, inner: Any, hook: Any) -> None:
        self._inner = inner
        self._hook = hook

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def find_one(self, *args: Any, **kwargs: Any) -> Any:
        doc = await self._inner.find_one(*args, **kwargs)
        hook, self._hook = self._hook, None
        if hook is not None:
            await hook()
        return doc


class _RacingRepo(MongoBillingLedgerRepository):
    def __init__(self, db: Any, hook: Any) -> None:
        super().__init__(db)
        self._race_hook = hook

    @property
    def ledger_payments(self) -> Any:
        return _RacingPaymentsCollection(
            self._db[self.ledger_payments_collection_name], self._race_hook
        )


@pytest.mark.asyncio
async def test_concurrent_allocations_cannot_double_spend_one_payment(db, acad) -> None:
    """Two writers racing on one payment must not both allocate its full funds."""
    seed = MongoBillingLedgerRepository(db)
    await seed.create_invoice(_invoice("inv-518-a", acad), lines=[], idempotency_key="inv:518:a")
    await seed.create_invoice(_invoice("inv-518-b", acad), lines=[], idempotency_key="inv:518:b")
    await seed.record_payment(_payment("pay-518", acad), idempotency_key="pay:518")

    async def competing_writer() -> None:
        """The winner: allocates the whole payment to invoice B."""
        await MongoBillingLedgerRepository(db).allocate_payment(
            payment_id="pay-518",
            invoice_id="inv-518-b",
            amount_cents=10_000,
            idempotency_key="alloc:518:webhook",
        )

    loser = _RacingRepo(db, competing_writer)

    with pytest.raises(ValueError):
        # Reads unapplied=10_000, the competing writer drains it to 0, and only
        # then does this allocation try to spend the snapshot's money.
        await loser.allocate_payment(
            payment_id="pay-518",
            invoice_id="inv-518-a",
            amount_cents=10_000,
            idempotency_key="alloc:518:legacy-match",
        )

    allocations = [doc async for doc in db["payment_allocations"].find({"payment_id": "pay-518"})]
    allocated = sum(int(doc["amount_cents"]) for doc in allocations)
    assert allocated <= 10_000, (
        f"payment pay-518 is worth 10000 cents but {allocated} cents were allocated "
        f"across {len(allocations)} allocation rows"
    )

    payment_doc = await db["ledger_payments"].find_one({"payment_id": "pay-518"})
    assert payment_doc is not None
    assert payment_doc["unapplied_amount_cents"] == 0
    assert int(payment_doc.get("over_allocated_cents", 0) or 0) == 0

    # The loser's invoice must not have been paid with money that was already spent.
    invoice_a = await db["invoices"].find_one({"invoice_id": "inv-518-a"})
    invoice_b = await db["invoices"].find_one({"invoice_id": "inv-518-b"})
    assert invoice_a is not None and invoice_b is not None
    assert invoice_b["status"] == "paid"
    assert invoice_a["status"] == "open"
    assert invoice_a["balance_due_cents"] == 10_000


@pytest.mark.asyncio
async def test_losing_allocation_leaves_no_orphan_allocation_row(db, acad) -> None:
    """The rolled-back allocation row is removed, so repairs stay consistent."""
    seed = MongoBillingLedgerRepository(db)
    await seed.create_invoice(_invoice("inv-518-c", acad), lines=[], idempotency_key="inv:518:c")
    await seed.create_invoice(_invoice("inv-518-d", acad), lines=[], idempotency_key="inv:518:d")
    await seed.record_payment(_payment("pay-518-2", acad), idempotency_key="pay:518:2")

    async def competing_writer() -> None:
        await MongoBillingLedgerRepository(db).allocate_payment(
            payment_id="pay-518-2",
            invoice_id="inv-518-d",
            amount_cents=10_000,
            idempotency_key="alloc:518:2:webhook",
        )

    loser = _RacingRepo(db, competing_writer)
    with pytest.raises(ValueError):
        await loser.allocate_payment(
            payment_id="pay-518-2",
            invoice_id="inv-518-c",
            amount_cents=10_000,
            idempotency_key="alloc:518:2:legacy-match",
        )

    orphan = await db["payment_allocations"].find_one(
        {"idempotency_key": "alloc:518:2:legacy-match"}
    )
    assert orphan is None


@pytest.mark.asyncio
async def test_uncontended_allocation_still_debits_the_payment(db, acad) -> None:
    """The new conditional payment write must not break the happy path."""
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(_invoice("inv-518-e", acad), lines=[], idempotency_key="inv:518:e")
    await repo.record_payment(_payment("pay-518-3", acad), idempotency_key="pay:518:3")

    result = await repo.allocate_payment(
        payment_id="pay-518-3",
        invoice_id="inv-518-e",
        amount_cents=10_000,
        idempotency_key="alloc:518:3",
    )

    assert result.invoice.status == "paid"
    assert result.payment.unapplied_amount_cents == 0
    payment_doc = await db["ledger_payments"].find_one({"payment_id": "pay-518-3"})
    assert payment_doc is not None
    assert payment_doc["unapplied_amount_cents"] == 0


@pytest.mark.asyncio
async def test_partial_allocations_of_one_payment_both_succeed(db, acad) -> None:
    """The guard rejects over-spend, not legitimate split allocations."""
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(
        _invoice("inv-518-f", acad, amount=4_000), lines=[], idempotency_key="inv:518:f"
    )
    await repo.create_invoice(
        _invoice("inv-518-g", acad, amount=4_000), lines=[], idempotency_key="inv:518:g"
    )
    await repo.record_payment(_payment("pay-518-4", acad), idempotency_key="pay:518:4")

    await repo.allocate_payment(
        payment_id="pay-518-4",
        invoice_id="inv-518-f",
        amount_cents=4_000,
        idempotency_key="alloc:518:4:f",
    )
    await repo.allocate_payment(
        payment_id="pay-518-4",
        invoice_id="inv-518-g",
        amount_cents=4_000,
        idempotency_key="alloc:518:4:g",
    )

    payment_doc = await db["ledger_payments"].find_one({"payment_id": "pay-518-4"})
    assert payment_doc is not None
    assert payment_doc["unapplied_amount_cents"] == 2_000
    assert int(payment_doc.get("over_allocated_cents", 0) or 0) == 0


@pytest.mark.asyncio
async def test_projection_repair_flags_over_allocation_instead_of_flooring(
    db, acad, caplog
) -> None:
    """A pre-existing double-spend must be surfaced, not normalised away."""
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(_invoice("inv-518-h", acad), lines=[], idempotency_key="inv:518:h")
    await repo.record_payment(_payment("pay-518-5", acad), idempotency_key="pay:518:5")

    # Seed the corrupted state a pre-#518 race would have left behind: one
    # 10_000-cent payment carrying two 10_000-cent allocations.
    for suffix, invoice_id in (("x", "inv-518-h"), ("y", "inv-518-h")):
        await db["payment_allocations"].insert_one(
            {
                "allocation_id": f"alloc-518-5-{suffix}",
                "academy_id": acad,
                "payment_id": "pay-518-5",
                "invoice_id": invoice_id,
                "amount_cents": 10_000,
                "created_at": NOW,
                "idempotency_key": f"alloc:518:5:{suffix}",
            }
        )

    with caplog.at_level(logging.ERROR):
        # Replaying an existing idempotency key runs the projection repair.
        await repo.allocate_payment(
            payment_id="pay-518-5",
            invoice_id="inv-518-h",
            amount_cents=10_000,
            idempotency_key="alloc:518:5:x",
        )

    payment_doc = await db["ledger_payments"].find_one({"payment_id": "pay-518-5"})
    assert payment_doc is not None
    assert payment_doc["unapplied_amount_cents"] == 0
    assert payment_doc["over_allocated_cents"] == 10_000
    assert any(
        "over-allocation" in record.getMessage() and "pay-518-5" in record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.ERROR
    ), "over-allocation must be logged at ERROR, not silently floored"


@pytest.mark.asyncio
async def test_reversal_repair_flags_over_allocation_instead_of_flooring(db, acad, caplog) -> None:
    """The reversal-side repair flags the same way the projection repair does."""
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(_invoice("inv-518-i", acad), lines=[], idempotency_key="inv:518:i")
    await repo.record_payment(_payment("pay-518-6", acad), idempotency_key="pay:518:6")
    for suffix in ("x", "y"):
        await db["payment_allocations"].insert_one(
            {
                "allocation_id": f"alloc-518-6-{suffix}",
                "academy_id": acad,
                "payment_id": "pay-518-6",
                "invoice_id": "inv-518-i",
                "amount_cents": 10_000,
                "created_at": NOW,
                "idempotency_key": f"alloc:518:6:{suffix}",
            }
        )

    with caplog.at_level(logging.ERROR):
        await repo._repair_payment_after_allocation_change(
            academy_id=acad,
            payment_id="pay-518-6",
            now=NOW,
        )

    payment_doc = await db["ledger_payments"].find_one({"payment_id": "pay-518-6"})
    assert payment_doc is not None
    assert payment_doc["unapplied_amount_cents"] == 0
    assert payment_doc["over_allocated_cents"] == 10_000
    assert any(
        "over-allocation" in record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.ERROR
    )


class _PaymentsHookedAtDebit:
    """Wraps ``ledger_payments`` and runs a competing writer just before the debit.

    The hook fires once, immediately before the first ``update_one`` — which in
    ``allocate_payment`` is the guarded debit. So it lands *after* this
    allocator has inserted its allocation row but *before* it consumes the
    funds, which is the window where a concurrent repair can see a reservation
    that has not been paid for yet.
    """

    def __init__(self, inner: Any, hook: Any) -> None:
        self._inner = inner
        self._hook = hook

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def update_one(self, *args: Any, **kwargs: Any) -> Any:
        hook, self._hook = self._hook, None
        if hook is not None:
            await hook()
        return await self._inner.update_one(*args, **kwargs)


class _RepoRacingAtDebit(MongoBillingLedgerRepository):
    def __init__(self, db: Any, hook: Any) -> None:
        super().__init__(db)
        self._debit_hook = hook

    @property
    def ledger_payments(self) -> Any:
        return _PaymentsHookedAtDebit(
            self._db[self.ledger_payments_collection_name], self._debit_hook
        )


@pytest.mark.asyncio
async def test_rejected_allocation_never_strands_the_payments_funds(db, acad) -> None:
    """A rolled-back allocation must give the money back, not silently lose it.

    An allocation row is visible to concurrent readers the instant it is
    inserted, and every repair path derives the unapplied balance as
    ``amount - refunded - allocated - credits``. A competing writer finishing in
    that window therefore writes the balance down on behalf of a row that has
    not been debited yet. If the losing allocator then merely dropped its row,
    those cents would be unspendable forever — and invisible, because the
    over-allocation flag only catches a surplus, never a deficit.

    Both writers here are individually affordable (4000 + 3000 out of 10000), so
    nothing about this interleaving is an over-spend.
    """
    seed = MongoBillingLedgerRepository(db)
    await seed.create_invoice(_invoice("inv-518-g", acad), lines=[], idempotency_key="inv:518:g")
    await seed.create_invoice(_invoice("inv-518-h", acad), lines=[], idempotency_key="inv:518:h")
    await seed.record_payment(_payment("pay-518-7", acad), idempotency_key="pay:518:7")

    async def competing_writer() -> None:
        await MongoBillingLedgerRepository(db).allocate_payment(
            payment_id="pay-518-7",
            invoice_id="inv-518-h",
            amount_cents=3_000,
            idempotency_key="alloc:518:7:webhook",
        )

    loser = _RepoRacingAtDebit(db, competing_writer)
    with pytest.raises(ValueError):
        await loser.allocate_payment(
            payment_id="pay-518-7",
            invoice_id="inv-518-g",
            amount_cents=4_000,
            idempotency_key="alloc:518:7:legacy-match",
        )

    allocations = [doc async for doc in db["payment_allocations"].find({"payment_id": "pay-518-7"})]
    allocated = sum(int(doc["amount_cents"]) for doc in allocations)
    payment_doc = await db["ledger_payments"].find_one({"payment_id": "pay-518-7"})
    assert payment_doc is not None
    assert allocated == 3_000
    assert payment_doc["unapplied_amount_cents"] == 7_000, (
        f"{7_000 - int(payment_doc['unapplied_amount_cents'])} cents of pay-518-7 were "
        "stranded by the rollback: allocated to nothing and no longer spendable"
    )
    assert int(payment_doc.get("over_allocated_cents", 0) or 0) == 0

    # ...and because the funds really are back, the caller's retry succeeds.
    retried = await MongoBillingLedgerRepository(db).allocate_payment(
        payment_id="pay-518-7",
        invoice_id="inv-518-g",
        amount_cents=4_000,
        idempotency_key="alloc:518:7:legacy-match",
    )
    assert retried.invoice.balance_due_cents == 6_000


@pytest.mark.asyncio
async def test_rejected_allocation_does_not_leave_a_healthy_payment_flagged(db, acad) -> None:
    """The over-allocation flag must not fire on a race the guard correctly rejected."""
    seed = MongoBillingLedgerRepository(db)
    await seed.create_invoice(_invoice("inv-518-i", acad), lines=[], idempotency_key="inv:518:i")
    await seed.create_invoice(_invoice("inv-518-j", acad), lines=[], idempotency_key="inv:518:j")
    await seed.record_payment(_payment("pay-518-8", acad), idempotency_key="pay:518:8")

    async def competing_writer() -> None:
        await MongoBillingLedgerRepository(db).allocate_payment(
            payment_id="pay-518-8",
            invoice_id="inv-518-j",
            amount_cents=10_000,
            idempotency_key="alloc:518:8:webhook",
        )

    loser = _RepoRacingAtDebit(db, competing_writer)
    with pytest.raises(ValueError):
        await loser.allocate_payment(
            payment_id="pay-518-8",
            invoice_id="inv-518-i",
            amount_cents=10_000,
            idempotency_key="alloc:518:8:legacy-match",
        )

    payment_doc = await db["ledger_payments"].find_one({"payment_id": "pay-518-8"})
    assert payment_doc is not None
    assert payment_doc["unapplied_amount_cents"] == 0
    assert int(payment_doc.get("over_allocated_cents", 0) or 0) == 0, (
        "the payment is healthy — 10000 in, 10000 allocated to one invoice — but it was "
        "left flagged as a double-spend, which makes the flag unactionable for ops"
    )


@pytest.mark.asyncio
async def test_refunded_money_cannot_be_allocated_again(db, acad) -> None:
    """The projection repair must not re-inflate the balance past the refund.

    ``_repair_allocation_projection`` runs at the end of every ``allocate_payment``
    and is the last write to ``unapplied_amount_cents``. It used to compute that
    balance ignoring ``refunded_cents``, so it handed the refunded money straight
    back as allocatable — a double-spend of the same funds needing no race at all.
    """
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(
        _invoice("inv-518-k", acad, 6_000), lines=[], idempotency_key="inv:518:k"
    )
    await repo.create_invoice(
        _invoice("inv-518-l", acad, 4_000), lines=[], idempotency_key="inv:518:l"
    )
    await repo.record_payment(_payment("pay-518-9", acad), idempotency_key="pay:518:9")
    # 4000 of the 10000 was refunded, so only 6000 is still spendable.
    await db["ledger_payments"].update_one(
        {"payment_id": "pay-518-9"},
        {"$set": {"refunded_cents": 4_000, "unapplied_amount_cents": 6_000}},
    )

    await repo.allocate_payment(
        payment_id="pay-518-9",
        invoice_id="inv-518-k",
        amount_cents=6_000,
        idempotency_key="alloc:518:9:a",
    )
    payment_doc = await db["ledger_payments"].find_one({"payment_id": "pay-518-9"})
    assert payment_doc is not None
    assert payment_doc["unapplied_amount_cents"] == 0, (
        "the refunded 4000 was handed back as spendable by the projection repair"
    )

    with pytest.raises(ValueError):
        await repo.allocate_payment(
            payment_id="pay-518-9",
            invoice_id="inv-518-l",
            amount_cents=4_000,
            idempotency_key="alloc:518:9:b",
        )

    allocations = [doc async for doc in db["payment_allocations"].find({"payment_id": "pay-518-9"})]
    allocated = sum(int(doc["amount_cents"]) for doc in allocations)
    assert allocated == 6_000, (
        f"{allocated} cents were allocated from a payment worth only 6000 after its refund"
    )


@pytest.mark.asyncio
async def test_refunded_allocated_payment_is_not_flagged_as_over_allocated(db, acad) -> None:
    """Refunds must not masquerade as double-spends in the flag.

    Allocations survive a refund by design (``_on_charge_refunded_ledger``: the
    payment did happen). Deriving the flag from ``amount - refunded - allocated``
    would therefore stamp every refunded-but-allocated payment as a double-spend
    and bury the genuine ones in the post-deploy audit.
    """
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(_invoice("inv-518-m", acad), lines=[], idempotency_key="inv:518:m")
    await repo.record_payment(_payment("pay-518-10", acad), idempotency_key="pay:518:10")
    await repo.allocate_payment(
        payment_id="pay-518-10",
        invoice_id="inv-518-m",
        amount_cents=10_000,
        idempotency_key="alloc:518:10",
    )
    await db["ledger_payments"].update_one(
        {"payment_id": "pay-518-10"}, {"$set": {"refunded_cents": 10_000}}
    )

    await repo._repair_payment_after_allocation_change(
        academy_id=acad, payment_id="pay-518-10", now=NOW
    )

    payment_doc = await db["ledger_payments"].find_one({"payment_id": "pay-518-10"})
    assert payment_doc is not None
    assert payment_doc["unapplied_amount_cents"] == 0
    assert payment_doc["over_allocated_cents"] == 0
