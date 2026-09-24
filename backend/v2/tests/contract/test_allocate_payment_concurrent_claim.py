"""#931: two callers sharing ONE allocation idempotency key, on a real mongod.

``MongoBillingLedgerRepository.allocate_payment`` claims an allocation by
inserting the ``payment_allocations`` row under the unique
``(academy_id, idempotency_key)`` index (0091). The claim itself was atomic,
but the loser of the insert went straight to ``_existing_allocation_result``,
whose repair re-derived the invoice and the payment from every visible
allocation row (the winner's included) and ``$set`` them unconditionally while
the winner was still between its insert and its guarded writes. The winner's
debit / invoice CAS then no longer matched its snapshot, and
``_rollback_pending_allocation`` deleted the winner's own row: the invoice was
left posted as paid with no allocation behind it, and a later retry under the
same key would allocate the money a second time.

Contract pinned here (real ``mongod``, every migration applied, ``real_db``):

* two concurrent ``allocate_payment`` calls with one key produce exactly ONE
  allocation row, both callers get that allocation back, the invoice is posted
  once and the payment is debited once;
* the exact #931 interleaving (the loser arrives between the winner's claim and
  its guarded writes) no longer rolls the winner back;
* a claim abandoned mid-flight (process died after the insert) is still taken
  over and healed once its lease has expired.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, LedgerPayment
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad-alloc-931"
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
TOTAL = 10_000


def _invoice(invoice_id: str, amount: int = TOTAL) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=ACAD,
        parent_id="parent-test-931",
        period="2026-09",
        status="open",
        subtotal_cents=amount,
        discount_cents=0,
        total_cents=amount,
        balance_due_cents=amount,
        currency="usd",
        due_date=date(2026, 9, 30),
        created_at=NOW,
        updated_at=NOW,
    )


def _payment(payment_id: str, amount: int = TOTAL) -> LedgerPayment:
    return LedgerPayment(
        payment_id=payment_id,
        academy_id=ACAD,
        parent_id="parent-test-931",
        amount_cents=amount,
        unapplied_amount_cents=amount,
        currency="usd",
        status="succeeded",
        payment_method="cash",
        paid_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


async def _seed(db: Any, suffix: str, *, payment_amount: int = TOTAL) -> tuple[str, str]:
    invoice_id = f"inv-931-{suffix}"
    payment_id = f"pay-931-{suffix}"
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(_invoice(invoice_id), lines=[], idempotency_key=f"inv:{suffix}")
    await repo.record_payment(_payment(payment_id, payment_amount), idempotency_key=f"pay:{suffix}")
    return invoice_id, payment_id


async def _state(
    db: Any, invoice_id: str, payment_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    allocations = [
        doc
        async for doc in db["payment_allocations"].find(
            {"academy_id": ACAD, "invoice_id": invoice_id}, {"_id": 0}
        )
    ]
    invoice = await db["invoices"].find_one({"academy_id": ACAD, "invoice_id": invoice_id})
    payment = await db["ledger_payments"].find_one({"academy_id": ACAD, "payment_id": payment_id})
    assert invoice is not None and payment is not None
    return allocations, invoice, payment


class _PausingPaymentsCollection:
    """``ledger_payments`` wrapper that runs a hook before the first write.

    The first ``update_one`` on this collection inside ``allocate_payment`` is
    the winner's guarded debit, i.e. the point right after the claim insert and
    before any guarded write: the window #931 describes.
    """

    def __init__(self, inner: Any, owner: _PausingRepo) -> None:
        self._inner = inner
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def update_one(self, *args: Any, **kwargs: Any) -> Any:
        hook, self._owner.hook = self._owner.hook, None
        if hook is not None:
            await hook()
        return await self._inner.update_one(*args, **kwargs)


class _PausingRepo(MongoBillingLedgerRepository):
    def __init__(self, db: Any, hook: Any, **kwargs: Any) -> None:
        super().__init__(db, **kwargs)
        self.hook = hook

    @property
    def ledger_payments(self) -> Any:
        return _PausingPaymentsCollection(self._db[self.ledger_payments_collection_name], self)


def _assert_one_allocation_posted_once(
    allocations: list[dict[str, Any]],
    invoice: dict[str, Any],
    payment: dict[str, Any],
    *,
    amount: int = TOTAL,
    payment_amount: int = TOTAL,
) -> None:
    assert len(allocations) == 1, f"expected ONE allocation row, found {allocations}"
    assert allocations[0]["amount_cents"] == amount
    assert invoice["balance_due_cents"] == TOTAL - amount
    assert invoice["status"] == ("paid" if amount == TOTAL else "partially_paid")
    assert payment["unapplied_amount_cents"] == payment_amount - amount
    assert int(payment.get("over_allocated_cents") or 0) == 0


async def test_concurrent_callers_with_one_key_allocate_once(real_db) -> None:
    """``asyncio.gather`` two callers with the same key, many times over."""
    with tenant_scope(ACAD):
        for round_no in range(15):
            invoice_id, payment_id = await _seed(real_db, f"gather-{round_no}")
            key = f"alloc:931:gather-{round_no}"

            def call(
                repo: MongoBillingLedgerRepository,
                invoice_id: str = invoice_id,
                payment_id: str = payment_id,
                key: str = key,
            ) -> Any:
                return repo.allocate_payment(
                    payment_id=payment_id,
                    invoice_id=invoice_id,
                    amount_cents=TOTAL,
                    idempotency_key=key,
                )

            first, second = await asyncio.gather(
                call(MongoBillingLedgerRepository(real_db)),
                call(MongoBillingLedgerRepository(real_db)),
            )
            allocations, invoice, payment = await _state(real_db, invoice_id, payment_id)

            assert first.allocation.allocation_id == second.allocation.allocation_id
            _assert_one_allocation_posted_once(allocations, invoice, payment)
            assert allocations[0]["allocation_id"] == first.allocation.allocation_id


async def test_loser_arriving_mid_claim_does_not_roll_the_winner_back(real_db) -> None:
    """The exact #931 interleaving, forced deterministically.

    The winner has inserted its claim row and is about to debit the payment.
    The loser (same key) runs now. Before the fix it repaired the projection
    from the winner's still-pending row and posted the invoice itself, the
    winner's guarded debit then missed, and the winner's rollback deleted its
    own row: invoice paid, no allocation, payment funds back to spendable.
    """
    with tenant_scope(ACAD):
        invoice_id, payment_id = await _seed(real_db, "interleave")
        key = "alloc:931:interleave"
        loser_task: list[asyncio.Task[Any]] = []

        def call(repo: MongoBillingLedgerRepository) -> Any:
            return repo.allocate_payment(
                payment_id=payment_id,
                invoice_id=invoice_id,
                amount_cents=TOTAL,
                idempotency_key=key,
            )

        async def loser_arrives() -> None:
            loser_task.append(asyncio.create_task(call(MongoBillingLedgerRepository(real_db))))
            # Give the loser ample time to reach (and, pre-fix, finish) its
            # repair while the winner is parked between claim and debit.
            await asyncio.sleep(0.5)

        winner_error: Exception | None = None
        try:
            winner = await call(_PausingRepo(real_db, loser_arrives))
        except ValueError as exc:  # pre-fix: "payment funds changed during allocation"
            winner_error = exc
        loser = await loser_task[0]
        allocations, invoice, payment = await _state(real_db, invoice_id, payment_id)

    assert winner_error is None, f"winner was rolled back by the same-key loser: {winner_error}"
    _assert_one_allocation_posted_once(allocations, invoice, payment)
    assert winner.allocation.allocation_id == loser.allocation.allocation_id
    assert loser.invoice.status == "paid" and loser.payment.unapplied_amount_cents == 0


class _StaleFirstLookupAllocations:
    """``payment_allocations`` whose FIRST key lookup misses.

    Models a same-key caller whose ``find_one`` ran just before the winner's
    claim insert, while its snapshot reads land after the winner committed.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.missed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def find_one(self, flt: Any, *args: Any, **kwargs: Any) -> Any:
        if not self.missed and isinstance(flt, dict) and "idempotency_key" in flt:
            self.missed = True
            return None
        return await self._inner.find_one(flt, *args, **kwargs)


class _StaleLookupDb:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.allocations = _StaleFirstLookupAllocations(inner["payment_allocations"])

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __getitem__(self, name: str) -> Any:
        if name == "payment_allocations":
            return self.allocations
        return self._inner[name]


async def test_loser_that_misses_the_claim_replays_it_instead_of_failing(real_db) -> None:
    """The loser's key lookup misses, but the winner commits before the loser
    reads the invoice and payment. The loser then computes against a paid
    invoice. Before the fix it raised "no payable invoice balance"; now it
    finds the winner's claim and returns the same allocation.
    """
    with tenant_scope(ACAD):
        invoice_id, payment_id = await _seed(real_db, "stale-lookup")
        key = "alloc:931:stale-lookup"
        winner = await MongoBillingLedgerRepository(real_db).allocate_payment(
            payment_id=payment_id, invoice_id=invoice_id, amount_cents=TOTAL, idempotency_key=key
        )
        stale_db = _StaleLookupDb(real_db)
        loser = await MongoBillingLedgerRepository(stale_db).allocate_payment(
            payment_id=payment_id, invoice_id=invoice_id, amount_cents=TOTAL, idempotency_key=key
        )
        allocations, invoice, payment = await _state(real_db, invoice_id, payment_id)

    assert stale_db.allocations.missed
    assert loser.allocation.allocation_id == winner.allocation.allocation_id
    _assert_one_allocation_posted_once(allocations, invoice, payment)


async def test_partial_allocation_race_keeps_the_payment_remainder(real_db) -> None:
    """Same interleaving on a payment larger than the invoice: no double debit."""
    with tenant_scope(ACAD):
        invoice_id, payment_id = await _seed(real_db, "partial", payment_amount=25_000)
        key = "alloc:931:partial"
        loser_task: list[asyncio.Task[Any]] = []

        def call(repo: MongoBillingLedgerRepository) -> Any:
            return repo.allocate_payment(
                payment_id=payment_id,
                invoice_id=invoice_id,
                amount_cents=4_000,
                idempotency_key=key,
            )

        async def loser_arrives() -> None:
            loser_task.append(asyncio.create_task(call(MongoBillingLedgerRepository(real_db))))
            await asyncio.sleep(0.5)

        winner = await call(_PausingRepo(real_db, loser_arrives))
        loser = await loser_task[0]
        allocations, invoice, payment = await _state(real_db, invoice_id, payment_id)

    _assert_one_allocation_posted_once(
        allocations, invoice, payment, amount=4_000, payment_amount=25_000
    )
    assert winner.allocation.allocation_id == loser.allocation.allocation_id
    assert winner.payment.unapplied_amount_cents == 21_000
    assert loser.payment.unapplied_amount_cents == 21_000


async def test_abandoned_claim_is_taken_over_after_its_lease(real_db) -> None:
    """A claim whose owner died after the insert is healed by the next retry."""
    with tenant_scope(ACAD):
        invoice_id, payment_id = await _seed(real_db, "abandoned")
        key = "alloc:931:abandoned"

        class _Died(Exception):
            pass

        async def die() -> None:
            raise _Died

        # The first caller inserts its claim row, then "dies" before any
        # guarded write: row pending, payment not debited, invoice not posted.
        died = False
        try:
            await _PausingRepo(real_db, die).allocate_payment(
                payment_id=payment_id,
                invoice_id=invoice_id,
                amount_cents=TOTAL,
                idempotency_key=key,
            )
        except _Died:
            died = True
        assert died, "abandoning caller should have died mid-claim"

        later = datetime.now(UTC) + timedelta(days=1)
        retry = await MongoBillingLedgerRepository(real_db, clock=lambda: later).allocate_payment(
            payment_id=payment_id,
            invoice_id=invoice_id,
            amount_cents=TOTAL,
            idempotency_key=key,
        )
        allocations, invoice, payment = await _state(real_db, invoice_id, payment_id)

    _assert_one_allocation_posted_once(allocations, invoice, payment)
    assert retry.allocation.allocation_id == allocations[0]["allocation_id"]
