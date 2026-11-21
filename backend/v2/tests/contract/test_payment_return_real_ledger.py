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
        event_id="evt",
        pi_id=pi,
        payment=payment,
        amount_cents=10_000,
        return_code="R01",
        source_key=None,
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


class _Audit:
    def __init__(self, db) -> None:
        from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
            MongoBillingAuditLogRepository,
        )

        self._repo = MongoBillingAuditLogRepository(db)

    async def append(self, entry) -> None:
        await self._repo.append(entry)


@pytest.mark.asyncio
async def test_partial_return_of_unallocated_money_stops_it_being_spendable(real_db, acad) -> None:
    """L8: with no allocation there is no invoice for an attempt row, and the old
    branch returned before marking the payment, so the returned part stayed
    spendable. It is now marked partially refunded, with an audit entry, and a
    replay converges."""
    repo = MongoBillingLedgerRepository(real_db)
    await repo.record_payment(_payment(acad, "pi_part"), idempotency_key="p:part")
    uc = HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        outbox=FakeOutbox(),
        academy_id=acad,
        billing_ledger=repo,
        family_autopay=_Family(),
        billing_audit=_Audit(real_db),
        clock=lambda: NOW,
    )

    for _ in range(2):
        payment = await repo.get_payment_by_stripe_payment_intent_id("pi_part")
        assert payment is not None
        await uc._reverse_returned_payment(
            event_id="evt",
            pi_id="pi_part",
            payment=payment,
            amount_cents=4_000,
            return_code="R01",
            source_key=None,
        )

    after = await real_db["ledger_payments"].find_one({"payment_id": "pay-pi_part"})
    # The 6,000 the bank did not take back is still the family's money.
    assert (after["status"], after["refunded_cents"], after["unapplied_amount_cents"]) == (
        "partially_refunded",
        4_000,
        6_000,
    )
    audits = await real_db["billing_audit_log"].find({"payment_id": "pay-pi_part"}).to_list(10)
    assert [a["action"] for a in audits] == ["payment_return_unreconciled"]


@pytest.mark.asyncio
async def test_second_partial_return_raises_the_total_and_stale_events_never_lower_it(
    real_db, acad
) -> None:
    """Stripe's ``charge.amount_refunded`` is cumulative: a 4,000 return and then a
    3,000 return arrive as 4,000 and 7,000. The total ends at 7,000 whether the
    events replay or arrive out of order."""
    repo = MongoBillingLedgerRepository(real_db)
    await repo.record_payment(_payment(acad, "pi_two"), idempotency_key="p:two")
    uc = HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        outbox=FakeOutbox(),
        academy_id=acad,
        billing_ledger=repo,
        family_autopay=_Family(),
        billing_audit=_Audit(real_db),
        clock=lambda: NOW,
    )

    for cumulative in (4_000, 7_000, 7_000, 4_000):
        payment = await repo.get_payment_by_stripe_payment_intent_id("pi_two")
        assert payment is not None
        await uc._reverse_returned_payment(
            event_id="evt",
            pi_id="pi_two",
            payment=payment,
            amount_cents=cumulative,
            return_code="R01",
            source_key=None,
        )

    after = await real_db["ledger_payments"].find_one({"payment_id": "pay-pi_two"})
    assert (after["status"], after["refunded_cents"], after["unapplied_amount_cents"]) == (
        "partially_refunded",
        7_000,
        3_000,
    )
    audits = await real_db["billing_audit_log"].find({"payment_id": "pay-pi_two"}).to_list(10)
    assert sorted(a["after"]["returned_cents"] for a in audits) == [4_000, 7_000]


@pytest.mark.asyncio
async def test_reopened_invoice_moves_both_dates_and_no_ladder_opens_before_then(
    real_db, acad
) -> None:
    """L8: reopen day + 5 for the due date AND the autopay charge stamp, or the old
    Jan 1 stamp re-arms the ladder the moment autopay resumes."""
    from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
        MongoDunningStateRepository,
    )

    repo = MongoBillingLedgerRepository(real_db)
    invoice = _invoice(acad, "inv-pi_reopen").model_copy(
        update={
            "enrollment_id": "enr-reopen",
            "due_date": date(2026, 11, 5),
            "autopay_charge_date": date(2026, 11, 1),
        }
    )
    await repo.create_invoice(invoice, lines=[], idempotency_key="i:reopen")
    payment = await repo.record_payment(_payment(acad, "pi_reopen"), idempotency_key="p:reopen")
    await repo.allocate_payment(
        payment_id=payment.payment_id,
        invoice_id="inv-pi_reopen",
        amount_cents=10_000,
        idempotency_key="autopay-alloc:pi_reopen",
    )
    await real_db["student_billing_enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enr-reopen",
            "student_id": "student-1",
            "parent_id": "parent-1",
            "session_type_id": "st-1",
            "autopay_enrollment_status": "active",
        }
    )
    uc = HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        outbox=FakeOutbox(),
        academy_id=acad,
        billing_ledger=repo,
        family_autopay=_Family(),
        clock=lambda: NOW,
    )

    await _return(uc, repo, "pi_reopen")

    reopened = await repo.get_invoice("inv-pi_reopen")
    assert reopened is not None and reopened.status == "open"
    assert (reopened.due_date, reopened.autopay_charge_date) == (
        date(2026, 11, 20),
        date(2026, 11, 20),
    )
    ladder = MongoDunningStateRepository(real_db)
    assert await ladder.prepare_due_states(now=datetime(2026, 11, 19, 12, tzinfo=UTC), limit=5) == 0
    assert await ladder.prepare_due_states(now=datetime(2026, 11, 20, 12, tzinfo=UTC), limit=5) == 1


@pytest.mark.asyncio
async def test_refund_then_dispute_sum_and_neither_replay_double_counts(real_db, acad) -> None:
    """A dispute amount is not cumulative: a 4,000 refund then a 3,000 dispute on
    the same payment is 7,000 taken back. Replaying either, in any order, keeps it."""
    repo = MongoBillingLedgerRepository(real_db)
    await repo.record_payment(_payment(acad, "pi_mix"), idempotency_key="p:mix")
    uc = HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        outbox=FakeOutbox(),
        academy_id=acad,
        billing_ledger=repo,
        family_autopay=_Family(),
        billing_audit=_Audit(real_db),
        clock=lambda: NOW,
    )
    refund = {"amount_cents": 4_000, "return_code": "R01", "source_key": None}
    dispute = {
        "amount_cents": 3_000,
        "return_code": "dispute:fraudulent",
        "source_key": "dispute:dp_1",
    }

    for step in (refund, dispute, dispute, refund, dispute):
        payment = await repo.get_payment_by_stripe_payment_intent_id("pi_mix")
        assert payment is not None
        await uc._reverse_returned_payment(event_id="evt", pi_id="pi_mix", payment=payment, **step)

    after = await real_db["ledger_payments"].find_one({"payment_id": "pay-pi_mix"})
    assert (after["status"], after["refunded_cents"], after["unapplied_amount_cents"]) == (
        "partially_refunded",
        7_000,
        3_000,
    )
    audits = await real_db["billing_audit_log"].find({"payment_id": "pay-pi_mix"}).to_list(10)
    assert sorted(a["after"]["returned_cents"] for a in audits) == [3_000, 4_000]


@pytest.mark.asyncio
async def test_a_plain_refund_after_a_dispute_adds_on_top_and_never_lowers_it(
    real_db, acad
) -> None:
    """Review fix: ``charge.refunded`` carries the charge's own running total, not
    the payment's. A 3,000 dispute then a 2,000 refund is 5,000 taken back, never 2,000."""
    repo = MongoBillingLedgerRepository(real_db)
    await repo.record_payment(_payment(acad, "pi_dr"), idempotency_key="p:dr")
    uc = HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        outbox=FakeOutbox(),
        academy_id=acad,
        billing_ledger=repo,
        family_autopay=_Family(),
        billing_audit=_Audit(real_db),
        clock=lambda: NOW,
    )
    payment = await repo.get_payment_by_stripe_payment_intent_id("pi_dr")
    assert payment is not None
    await uc._reverse_returned_payment(
        event_id="evt-d",
        pi_id="pi_dr",
        payment=payment,
        amount_cents=3_000,
        return_code="dispute:fraudulent",
        source_key="dispute:dp_9",
    )

    for _ in range(2):
        await uc._on_charge_refunded_ledger("pi_dr", {"amount_refunded": 2_000})

    after = await real_db["ledger_payments"].find_one({"payment_id": "pay-pi_dr"})
    assert (after["status"], after["refunded_cents"]) == ("partially_refunded", 5_000)


class _AuditFailingOnce(_Audit):
    """The audit write dies once, as if the worker crashed mid-return."""

    def __init__(self, db) -> None:
        super().__init__(db)
        self.failed = False

    async def append(self, entry) -> None:
        if not self.failed and entry.audit_id.endswith("dispute:dp_60"):
            self.failed = True
            raise RuntimeError("audit write failed")
        await super().append(entry)


@pytest.mark.asyncio
async def test_a_return_that_completes_the_refund_keeps_its_audit_and_alert_on_retry(
    real_db, acad, monkeypatch
) -> None:
    """PR #1181 review: $40 refunded, then a $60 dispute takes the payment to fully
    refunded. Once it reads refunded a replay stops early, so the audit row and
    alert must land before the money moves, or a failed audit write loses them."""
    from backend.v2.contexts.billing.application.use_cases import handle_webhook_event

    alerts: list[str] = []
    monkeypatch.setattr(
        handle_webhook_event,
        "capture_message",
        lambda message, level="error", **_: alerts.append(message),
    )
    repo = MongoBillingLedgerRepository(real_db)
    await repo.record_payment(_payment(acad, "pi_full"), idempotency_key="p:full")
    audit = _AuditFailingOnce(real_db)
    uc = HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        outbox=FakeOutbox(),
        academy_id=acad,
        billing_ledger=repo,
        family_autopay=_Family(),
        billing_audit=audit,
        clock=lambda: NOW,
    )

    async def _return(amount: int, code: str, key: str | None) -> None:
        payment = await repo.get_payment_by_stripe_payment_intent_id("pi_full")
        assert payment is not None
        await uc._reverse_returned_payment(
            event_id="evt",
            pi_id="pi_full",
            payment=payment,
            amount_cents=amount,
            return_code=code,
            source_key=key,
        )

    await _return(4_000, "R01", None)
    with pytest.raises(RuntimeError):
        await _return(6_000, "dispute:fraudulent", "dispute:dp_60")
    mid = await real_db["ledger_payments"].find_one({"payment_id": "pay-pi_full"})
    assert mid["refunded_cents"] == 4_000  # nothing moved before the trail was written
    await _return(6_000, "dispute:fraudulent", "dispute:dp_60")
    await _return(6_000, "dispute:fraudulent", "dispute:dp_60")  # later replay: a no-op

    after = await real_db["ledger_payments"].find_one({"payment_id": "pay-pi_full"})
    assert (after["status"], after["refunded_cents"], after["unapplied_amount_cents"]) == (
        "refunded",
        10_000,
        0,
    )
    dispute_rows = await real_db["billing_audit_log"].count_documents(
        {"audit_id": "baud-payment-return:pi_full:dispute:dp_60"}
    )
    assert dispute_rows == 1
    assert len([a for a in alerts if "6000 of 10000" in a]) == 1
