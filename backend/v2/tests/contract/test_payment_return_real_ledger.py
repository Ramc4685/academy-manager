"""Payment returns against the REAL Mongo ledger (L1 fix round 2).

The in-memory fakes hid two bugs here: a full return left the clawed-back money
spendable as unapplied, and a crash inside the reversal left a replay with no
way to finish the invoice repair.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, LedgerPayment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.tests.contract.test_stripe_webhook_fixture_replay import (
    FakeDedup,
    FakeOutbox,
    FakePaymentRepo,
    FakeSubscriptionRepo,
)

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


class _Family:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def pause_family(self, **kw: str) -> int:
        self.calls.append(kw)
        return 1


def _invoice(acad: str, invoice_id: str) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=acad,
        parent_id="parent-1",
        period="2026-11",
        status="open",
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=10_000,
        currency="usd",
        due_date=date(2026, 11, 1),
        created_at=NOW,
        updated_at=NOW,
    )


def _payment(acad: str, pi: str, metadata: dict[str, str] | None = None) -> LedgerPayment:
    return LedgerPayment(
        payment_id=f"pay-{pi}",
        academy_id=acad,
        parent_id="parent-1",
        amount_cents=10_000,
        unapplied_amount_cents=10_000,
        currency="usd",
        status="succeeded",
        payment_method="stripe_autopay",
        stripe_payment_intent_id=pi,
        paid_at=NOW,
        metadata=metadata or {"funding_type": "us_bank_account"},
        created_at=NOW,
        updated_at=NOW,
    )


async def _paid_invoice(
    repo: MongoBillingLedgerRepository, acad: str, pi: str, metadata: dict[str, str] | None = None
) -> LedgerPayment:
    await repo.create_invoice(_invoice(acad, f"inv-{pi}"), lines=[], idempotency_key=f"i:{pi}")
    payment = await repo.record_payment(_payment(acad, pi, metadata), idempotency_key=f"p:{pi}")
    await repo.allocate_payment(
        payment_id=payment.payment_id,
        invoice_id=f"inv-{pi}",
        amount_cents=10_000,
        idempotency_key=f"autopay-alloc:{pi}",
    )
    return payment


def _handler(repo: MongoBillingLedgerRepository, acad: str) -> HandleWebhookEvent:
    return HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        outbox=FakeOutbox(),
        academy_id=acad,
        billing_ledger=repo,
        family_autopay=_Family(),
    )


async def _return(uc: HandleWebhookEvent, repo: MongoBillingLedgerRepository, pi: str) -> None:
    payment = await repo.get_payment_by_stripe_payment_intent_id(pi)
    assert payment is not None
    await uc._reverse_returned_payment(
        event_id="evt", pi_id=pi, payment=payment, amount_cents=10_000, return_code="R01"
    )


@pytest.mark.asyncio
async def test_full_return_leaves_no_spendable_unapplied_money(real_db, acad) -> None:
    repo = MongoBillingLedgerRepository(real_db)
    payment = await _paid_invoice(repo, acad, "pi_full")

    await _return(_handler(repo, acad), repo, "pi_full")

    after = await real_db["ledger_payments"].find_one({"payment_id": payment.payment_id})
    assert (after["status"], after["refunded_cents"], after["unapplied_amount_cents"]) == (
        "refunded",
        10_000,
        0,
    )
    invoice = await repo.get_invoice("inv-pi_full")
    assert invoice is not None and invoice.status == "open"
    with pytest.raises(Exception):  # noqa: B017 - any refusal; the money is gone
        await repo.allocate_payment(
            payment_id=payment.payment_id,
            invoice_id="inv-pi_full",
            amount_cents=10_000,
            idempotency_key="again:pi_full",
        )
    invoice = await repo.get_invoice("inv-pi_full")
    assert invoice is not None and invoice.status == "open"


@pytest.mark.asyncio
async def test_replay_after_the_refund_mark_failed_converges(real_db, acad) -> None:
    repo = MongoBillingLedgerRepository(real_db)
    await _paid_invoice(repo, acad, "pi_mark")
    uc = _handler(repo, acad)
    real_mark = repo.mark_payment_refunded
    calls = {"n": 0}

    async def flaky_mark(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("mongo blip")
        return await real_mark(*args, **kwargs)

    repo.mark_payment_refunded = flaky_mark  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await _return(uc, repo, "pi_mark")
    await _return(uc, repo, "pi_mark")

    payment = await repo.get_payment_by_stripe_payment_intent_id("pi_mark")
    assert payment is not None
    assert (payment.status, payment.unapplied_amount_cents) == ("refunded", 0)


@pytest.mark.asyncio
async def test_crash_after_the_refunded_mark_leaves_no_spendable_money(real_db, acad) -> None:
    """Codex P1 on #1178: a replay skips refunded payments, so the refunded
    marker and the cleared unapplied balance must land in one write."""
    repo = MongoBillingLedgerRepository(real_db)
    payment = await _paid_invoice(repo, acad, "pi_crash")
    uc = _handler(repo, acad)

    real_mark = repo.mark_payment_refunded

    async def crash(**_kwargs):
        raise RuntimeError("mongo blip after the refunded write")

    async def mark_then_crash(*args, **kwargs):
        # Only the recompute inside the refund mark fails; the reversal before it runs normally.
        repo._repair_payment_after_allocation_change = crash  # type: ignore[method-assign]
        return await real_mark(*args, **kwargs)

    repo.mark_payment_refunded = mark_then_crash  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await _return(uc, repo, "pi_crash")

    after = await real_db["ledger_payments"].find_one({"payment_id": payment.payment_id})
    assert (after["status"], after["unapplied_amount_cents"]) == ("refunded", 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_invoice_metadata", [False, True])
async def test_replay_after_a_crash_between_delete_and_invoice_repair_reopens_the_invoice(
    real_db, acad, with_invoice_metadata
) -> None:
    """Should-fix 2: the allocation is gone but the invoice still reads paid; the
    replay must finish the repair from the payment's reversal rows."""
    repo = MongoBillingLedgerRepository(real_db)
    metadata = {"funding_type": "us_bank_account"}
    if with_invoice_metadata:
        metadata["invoice_id"] = "inv-pi_crash"
    await _paid_invoice(repo, acad, "pi_crash", metadata)
    uc = _handler(repo, acad)
    real_repair = repo._repair_invoice_after_allocation_change
    calls = {"n": 0}

    async def flaky_repair(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("mongo blip")
        return await real_repair(**kwargs)

    repo._repair_invoice_after_allocation_change = flaky_repair  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await _return(uc, repo, "pi_crash")
    assert await real_db["payment_allocations"].count_documents({}) == 0
    assert (await repo.get_invoice("inv-pi_crash")).status == "paid"  # type: ignore[union-attr]

    await _return(uc, repo, "pi_crash")

    invoice = await repo.get_invoice("inv-pi_crash")
    payment = await repo.get_payment_by_stripe_payment_intent_id("pi_crash")
    assert invoice is not None and payment is not None
    assert (invoice.status, invoice.balance_due_cents) == ("open", 10_000)
    assert (payment.status, payment.unapplied_amount_cents) == ("refunded", 0)


@pytest.mark.asyncio
async def test_full_return_of_unallocated_money_leaves_nothing_spendable(real_db, acad) -> None:
    """Final risk check on #1178: no allocation and no invoice means the money was
    never applied, so a full return just refunds it instead of leaving it spendable."""
    repo = MongoBillingLedgerRepository(real_db)
    await repo.record_payment(_payment(acad, "pi_none"), idempotency_key="p:none")

    await _return(_handler(repo, acad), repo, "pi_none")

    after = await real_db["ledger_payments"].find_one({"payment_id": "pay-pi_none"})
    assert (after["status"], after["unapplied_amount_cents"]) == ("refunded", 0)


@pytest.mark.asyncio
async def test_return_naming_an_invoice_without_an_allocation_is_left_for_a_manual_look(
    real_db, acad
) -> None:
    """The invoice may read paid with no allocation to reverse: park it and count it
    on the "Bank returns to check" card."""
    repo = MongoBillingLedgerRepository(real_db)
    await repo.create_invoice(_invoice(acad, "inv-pi_meta"), lines=[], idempotency_key="i:meta")
    await repo.record_payment(
        _payment(acad, "pi_meta", {"funding_type": "us_bank_account", "invoice_id": "inv-pi_meta"}),
        idempotency_key="p:meta",
    )

    await _return(_handler(repo, acad), repo, "pi_meta")

    payment = await repo.get_payment_by_stripe_payment_intent_id("pi_meta")
    assert payment is not None and payment.status == "succeeded"
    attempt = await real_db["payment_attempts"].find_one({"invoice_id": "inv-pi_meta"})
    assert attempt is not None and attempt["failure_code"] == "unreconciled_payment_return"
