"""One autopay charge per family (L8 PR B), on a real mongod.

Siblings whose dunning rungs are due at the same time are charged as ONE
PaymentIntent: one payment, one allocation per invoice, one receipt, one notice.
Everything money-shaped runs on ``real_db`` with the real ledger and dunning
repositories (validators and partial unique indexes enforced); only Stripe is a
double, and it dedupes by idempotency key the way Stripe does, so a replayed key
returns the first PaymentIntent instead of charging again.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.add_invoice_line import AddInvoiceLine
from backend.v2.contexts.billing.application.use_cases.apply_late_fees import (
    LATE_FEE_LINE_TYPE,
    ApplyLateFees,
)
from backend.v2.contexts.billing.application.use_cases.charge_invoice_via_autopay import (
    ChargeInvoiceViaAutopay,
)
from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.application.use_cases.process_dunning_retries import (
    ProcessDunningRetries,
)
from backend.v2.contexts.billing.application.use_cases.reconcile_stripe_payment_intents import (
    ReconcileStripePaymentIntents,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.errors import StripeUnavailable
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice, LedgerPayment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
    MongoDunningStateRepository,
)
from backend.v2.tests.contract.test_stripe_webhook_fixture_replay import (
    FakeDedup,
    FakeOutbox,
    FakePaymentRepo,
    FakeSubscriptionRepo,
)

pytestmark = pytest.mark.asyncio

ACAD = "test-academy"
PARENT = "parent-fam"
# Before the wall clock, so webhook rows (stamped with the real now) read as later.
NOW = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


class _Stripe:
    """Stripe double that dedupes PaymentIntents by idempotency key."""

    def __init__(self, *outcomes: tuple[str, str | None], crash_once: bool = False) -> None:
        self.outcomes = list(outcomes)
        self.crash_once = crash_once
        self.calls: list[dict[str, Any]] = []
        self.by_key: dict[str, tuple[str, str, str | None]] = {}
        self.intents: dict[str, dict[str, Any]] = {}

    async def get_default_payment_method(self, *, academy_id: str, parent_id: str):
        return ("cus_fam", "pm_fam")

    async def retrieve_payment_method(self, payment_method_id: str, **_: Any) -> dict[str, Any]:
        return {"id": payment_method_id, "type": "card", "card": {"funding": "credit"}}

    async def create_off_session_payment_intent(
        self, *, amount_cents: int, idempotency_key: str, metadata: dict[str, str], **_: Any
    ) -> tuple[str, str, str | None]:
        self.calls.append({"amount_cents": amount_cents, "key": idempotency_key})
        if idempotency_key not in self.by_key:
            status, code = self.outcomes.pop(0) if self.outcomes else ("succeeded", None)
            pi_id = f"pi_{len(self.by_key) + 1}"
            self.by_key[idempotency_key] = (pi_id, status, code)
            self.intents[pi_id] = {"amount_cents": amount_cents, "metadata": dict(metadata)}
        if self.crash_once:
            # Stripe took the charge; the answer never reached us.
            self.crash_once = False
            raise RuntimeError("connection reset after Stripe accepted the request")
        return self.by_key[idempotency_key]


class _TimeoutStripe(_Stripe):
    """Stripe accepted the PaymentIntent, but the answer timed out once."""

    def __init__(self, exc: type[Exception]) -> None:
        super().__init__()
        self.exc: type[Exception] | None = exc

    async def create_off_session_payment_intent(self, **kwargs: Any) -> tuple[str, str, str | None]:
        result = await super().create_off_session_payment_intent(**kwargs)
        if self.exc is not None:
            exc, self.exc = self.exc, None
            raise exc("read timeout after Stripe accepted the request")
        return result


class _HouseSettings:
    async def get(self) -> BillingSettings:
        return BillingSettings(academy_id=ACAD, allow_platform_charge_fallback=True)


class _Notifier:
    async def send_dunning_notice(self, **_: Any) -> None:  # pragma: no cover - outbox wired
        raise AssertionError("notices go through the outbox")


async def _seed(
    real_db: Any,
    invoice_id: str,
    *,
    cents: int = 10_000,
    parent_id: str = PARENT,
    due: date = date(2026, 6, 25),
    period: str = "2026-06",
) -> None:
    invoice = LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=ACAD,
        parent_id=parent_id,
        student_id=f"student-{invoice_id}",
        enrollment_id=f"enr-{invoice_id}",
        period=period,
        status="open",
        subtotal_cents=cents,
        discount_cents=0,
        total_cents=cents,
        balance_due_cents=cents,
        currency="usd",
        due_date=due,
        created_at=NOW,
        updated_at=NOW,
    )
    line = InvoiceLine(
        line_id=f"{invoice_id}-tuition",
        academy_id=ACAD,
        invoice_id=invoice_id,
        line_type="tuition",
        description="June tuition",
        quantity=1,
        unit_amount_cents=cents,
        amount_cents=cents,
        created_at=NOW,
    )
    await MongoBillingLedgerRepository(real_db).create_invoice(
        invoice, lines=[line], idempotency_key=f"seed:{invoice_id}"
    )
    await real_db["student_billing_enrollments"].insert_one(
        {
            "academy_id": ACAD,
            "enrollment_id": f"enr-{invoice_id}",
            "student_id": f"student-{invoice_id}",
            "parent_id": parent_id,
            "session_type_id": "session-type-1",
            "billing_start_date": datetime(2026, 6, 1, tzinfo=UTC),
            "status": "active",
            "autopay_enrollment_status": "active",
            "enrolled_at": NOW,
            "updated_at": NOW,
        }
    )


def _charge(real_db: Any, stripe: _Stripe) -> ChargeInvoiceViaAutopay:
    return ChargeInvoiceViaAutopay(
        ledger=MongoBillingLedgerRepository(real_db),
        stripe=stripe,
        settings=_HouseSettings(),
        connected_accounts=MongoConnectedAccountRepository(real_db),
        clock=lambda: NOW,
    )


async def _tick(real_db: Any, stripe: _Stripe, outbox: FakeOutbox, at: datetime = NOW) -> Any:
    repo = MongoDunningStateRepository(real_db)
    await repo.prepare_due_states(now=at, limit=100)
    return await ProcessDunningRetries(
        dunning=repo,
        charge_invoice=_charge(real_db, stripe),
        notifier=_Notifier(),
        outbox=outbox,
        clock=lambda: at,
    ).execute(limit=20, worker_id="worker-1")


def _webhook(real_db: Any, outbox: FakeOutbox) -> HandleWebhookEvent:
    return HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        outbox=outbox,
        academy_id=ACAD,
        billing_ledger=MongoBillingLedgerRepository(real_db),
    )


def _pi_event(
    event_id: str,
    event_type: str,
    pi_id: str,
    amount: int,
    metadata: dict[str, str],
    *,
    ach: bool = False,
    **extra: Any,
) -> bytes:
    pi: dict[str, Any] = {
        "id": pi_id,
        "object": "payment_intent",
        "amount": amount,
        "currency": "usd",
        "metadata": metadata,
        **extra,
    }
    if ach:
        pi["payment_method_types"] = ["us_bank_account"]
    return json.dumps(
        {"id": event_id, "type": event_type, "livemode": False, "data": {"object": pi}}
    ).encode()


def _family_metadata(*invoice_ids: str, group: str = "grp-1") -> dict[str, str]:
    return {
        "invoice_ids": ",".join(sorted(invoice_ids)),
        "academy_id": ACAD,
        "parent_id": PARENT,
        "source": "autopay",
        "charge_group_id": group,
    }


async def _invoice(real_db: Any, invoice_id: str) -> dict[str, Any]:
    doc = await real_db["invoices"].find_one({"academy_id": ACAD, "invoice_id": invoice_id})
    assert doc is not None
    return doc


def _notices(outbox: FakeOutbox) -> list[Any]:
    return [e for e in outbox.events if e.name == "Billing.DunningNoticeRequested"]


async def test_two_siblings_are_one_charge_one_payment_two_allocations_one_receipt(
    real_db, acad
) -> None:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b", cents=8_000)
    stripe = _Stripe(("succeeded", None))
    outbox = FakeOutbox()

    result = await _tick(real_db, stripe, outbox)

    assert result.succeeded == 2
    assert len(stripe.calls) == 1
    (pi_id,) = stripe.intents
    assert stripe.intents[pi_id]["amount_cents"] == 18_000
    assert stripe.intents[pi_id]["metadata"]["invoice_ids"] == "inv-a,inv-b"
    for invoice_id in ("inv-a", "inv-b"):
        assert (await _invoice(real_db, invoice_id))["status"] == "paid"

    # The settle webhook (and its redelivery) adds nothing but the one receipt.
    body = _pi_event(
        "evt_fam_ok",
        "payment_intent.succeeded",
        pi_id,
        18_000,
        stripe.intents[pi_id]["metadata"],
    )
    await _webhook(real_db, outbox).execute(body, "test_signature")
    await _webhook(real_db, outbox).execute(body, "test_signature")

    payments = await real_db["ledger_payments"].find({"academy_id": ACAD}).to_list(None)
    assert [p["payment_id"] for p in payments] == [f"ledger-pay-autopay:{pi_id}"]
    allocations = await real_db["payment_allocations"].find({"academy_id": ACAD}).to_list(None)
    assert sorted((a["invoice_id"], a["amount_cents"]) for a in allocations) == [
        ("inv-a", 10_000),
        ("inv-b", 8_000),
    ]
    receipts = [e for e in outbox.events if e.name == "Billing.PaymentReceiptRequested"]
    assert len(receipts) == 1
    assert receipts[0].payload.invoice_ids == ("inv-a", "inv-b")
    states = await real_db["dunning_states"].find({"academy_id": ACAD}).to_list(None)
    assert {s["status"] for s in states} == {"resolved"}


async def test_a_declined_family_charge_sends_one_notice_and_records_each_invoice(
    real_db, acad
) -> None:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b")
    stripe = _Stripe(("requires_payment_method", "card_declined"))
    outbox = FakeOutbox()

    result = await _tick(real_db, stripe, outbox)

    assert (result.failed, result.notifications_sent) == (2, 1)
    (notice,) = _notices(outbox)
    assert notice.payload.invoice_ids == ("inv-a", "inv-b")
    assert notice.payload.balance_due_cents == 20_000
    failed = await real_db["payment_attempts"].find({"status": "failed"}).to_list(None)
    assert sorted(a["invoice_id"] for a in failed) == ["inv-a", "inv-b"]

    # The failure webhook replays onto one row per invoice, and no second notice.
    (pi_id,) = stripe.intents
    body = _pi_event(
        "evt_fam_declined",
        "payment_intent.payment_failed",
        pi_id,
        20_000,
        stripe.intents[pi_id]["metadata"],
        last_payment_error={"code": "card_declined", "message": "Declined"},
    )
    await _webhook(real_db, outbox).execute(body, "test_signature")
    await _webhook(real_db, outbox).execute(body, "test_signature")
    hook_rows = (
        await real_db["payment_attempts"]
        .find({"idempotency_key": {"$regex": "^autopay-failed:"}})
        .to_list(None)
    )
    assert sorted(a["invoice_id"] for a in hook_rows) == ["inv-a", "inv-b"]
    assert len(_notices(outbox)) == 1
    states = await real_db["dunning_states"].find({"academy_id": ACAD}).to_list(None)
    assert {s["attempt_count"] for s in states} == {1}


async def _ach_family(real_db: Any) -> tuple[_Stripe, FakeOutbox, str, dict[str, str]]:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b")
    stripe = _Stripe(("processing", None))
    outbox = FakeOutbox()
    result = await _tick(real_db, stripe, outbox)
    assert result.parked == 2
    (pi_id,) = stripe.intents
    metadata = stripe.intents[pi_id]["metadata"]
    processing = _pi_event(
        "evt_ach_proc", "payment_intent.processing", pi_id, 20_000, metadata, ach=True
    )
    await _webhook(real_db, outbox).execute(processing, "test_signature")
    await _webhook(real_db, outbox).execute(processing, "test_signature")
    rows = (
        await real_db["payment_attempts"]
        .find({"idempotency_key": {"$regex": "^autopay-processing:"}})
        .to_list(None)
    )
    assert sorted(a["invoice_id"] for a in rows) == ["inv-a", "inv-b"]
    return stripe, outbox, pi_id, metadata


async def test_family_bank_debit_settles_both_invoices_once_with_replay(real_db, acad) -> None:
    stripe, outbox, pi_id, metadata = await _ach_family(real_db)

    settled = _pi_event("evt_ach_ok", "payment_intent.succeeded", pi_id, 20_000, metadata, ach=True)
    await _webhook(real_db, outbox).execute(settled, "test_signature")
    await _webhook(real_db, outbox).execute(settled, "test_signature")
    await _tick(real_db, stripe, outbox, at=NOW + timedelta(hours=1))

    assert len(stripe.calls) == 1
    for invoice_id in ("inv-a", "inv-b"):
        assert (await _invoice(real_db, invoice_id))["status"] == "paid"
    assert await real_db["ledger_payments"].count_documents({"academy_id": ACAD}) == 1
    assert await real_db["payment_allocations"].count_documents({"academy_id": ACAD}) == 2
    assert _notices(outbox) == []


async def test_family_bank_debit_failure_sends_each_final_notice_once(real_db, acad) -> None:
    stripe, outbox, pi_id, metadata = await _ach_family(real_db)

    failed = _pi_event(
        "evt_ach_fail",
        "payment_intent.payment_failed",
        pi_id,
        20_000,
        metadata,
        ach=True,
        last_payment_error={"code": "payment_method_provider_decline", "message": "Declined"},
    )
    await _webhook(real_db, outbox).execute(failed, "test_signature")
    await _webhook(real_db, outbox).execute(failed, "test_signature")
    first = await _tick(real_db, stripe, outbox, at=NOW + timedelta(hours=1))
    await _tick(real_db, stripe, outbox, at=NOW + timedelta(hours=2))

    assert first.failed == 2
    assert len(stripe.calls) == 1  # never debited again while settling
    # A hard decline turns autopay off: each invoice gets its own final notice,
    # so one member's notice never swallows the other's (replays add none).
    notices = _notices(outbox)
    assert sorted(n.payload.invoice_id for n in notices) == ["inv-a", "inv-b"]
    assert all(n.payload.terminal and n.payload.invoice_ids == () for n in notices)
    assert all(n.payload.bank_debit for n in notices)
    states = await real_db["dunning_states"].find({"academy_id": ACAD}).to_list(None)
    assert {s["attempt_count"] for s in states} == {1}


async def test_stale_lease_replay_with_a_new_sibling_makes_no_second_charge(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b")
    repo = MongoDunningStateRepository(real_db)
    await repo.prepare_due_states(now=NOW, limit=100)
    lead = await repo.claim_next_due(now=NOW, worker_id="w1", charge_group_id="grp-stale")
    assert lead is not None
    members = [
        lead,
        *await repo.claim_group_siblings(
            lead=lead[1], now=NOW, worker_id="w1", rejoin=False, period="2026-06"
        ),
    ]
    assert sorted(invoice.invoice_id for invoice, _ in members) == ["inv-a", "inv-b"]
    stripe = _Stripe(("succeeded", None), crash_once=True)
    with pytest.raises(RuntimeError):
        await _charge(real_db, stripe).execute_family(
            [invoice.invoice_id for invoice, _ in members],
            charge_group_id="grp-stale",
            retry_scopes={
                invoice.invoice_id: f"dunning-attempt:{state.processing_attempt_no}"
                for invoice, state in members
            },
        )
    # The worker died holding both leases; a third child's invoice arrives.
    await _seed(real_db, "inv-c", cents=5_000)

    await _tick(real_db, stripe, FakeOutbox(), at=NOW + timedelta(minutes=31))

    family_keys = [c["key"] for c in stripe.calls if c["amount_cents"] == 20_000]
    assert len(family_keys) == 2 and len(set(family_keys)) == 1  # same key, replayed
    assert sorted(i["amount_cents"] for i in stripe.intents.values()) == [5_000, 20_000]
    for invoice_id in ("inv-a", "inv-b", "inv-c"):
        assert (await _invoice(real_db, invoice_id))["status"] == "paid"
    assert await real_db["ledger_payments"].count_documents({"academy_id": ACAD}) == 2


async def test_sibling_paid_mid_flight_turns_the_surplus_into_credit(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b")
    ledger = MongoBillingLedgerRepository(real_db)
    # Paid at the front desk while the family debit was settling.
    manual = await ledger.record_payment(
        LedgerPayment(
            payment_id="pay-desk-b",
            academy_id=ACAD,
            parent_id=PARENT,
            amount_cents=10_000,
            unapplied_amount_cents=10_000,
            currency="usd",
            status="succeeded",
            payment_method="cash",
            paid_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        ),
        idempotency_key="desk:b",
    )
    await ledger.allocate_payment(
        payment_id=manual.payment_id,
        invoice_id="inv-b",
        amount_cents=10_000,
        idempotency_key="desk-alloc:b",
    )

    body = _pi_event(
        "evt_mid",
        "payment_intent.succeeded",
        "pi_mid",
        20_000,
        _family_metadata("inv-a", "inv-b"),
        ach=True,
    )
    await _webhook(real_db, FakeOutbox()).execute(body, "test_signature")

    assert (await _invoice(real_db, "inv-a"))["status"] == "paid"
    credits = await real_db["account_credit_ledger"].find({"academy_id": ACAD}).to_list(None)
    assert [c["amount_cents"] for c in credits] == [10_000]
    payment = await real_db["ledger_payments"].find_one({"payment_id": "ledger-pay-autopay:pi_mid"})
    assert payment["unapplied_amount_cents"] == 0


async def test_legacy_single_invoice_payment_intent_settles_on_its_bare_key(real_db, acad) -> None:
    """A charge made before this deploy names one ``invoice_id``: it settles exactly
    as it always did, on the bare ``autopay-alloc:{pi}`` key."""
    await _seed(real_db, "inv-legacy")
    metadata = {
        "invoice_id": "inv-legacy",
        "academy_id": ACAD,
        "parent_id": PARENT,
        "source": "autopay",
    }
    body = _pi_event("evt_legacy", "payment_intent.succeeded", "pi_legacy", 10_000, metadata)
    await _webhook(real_db, FakeOutbox()).execute(body, "test_signature")

    allocations = await real_db["payment_allocations"].find({"academy_id": ACAD}).to_list(None)
    assert [(a["invoice_id"], a["idempotency_key"]) for a in allocations] == [
        ("inv-legacy", "autopay-alloc:pi_legacy")
    ]
    assert (await _invoice(real_db, "inv-legacy"))["status"] == "paid"


async def test_family_bank_return_reopens_both_invoices_with_one_notice(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b", cents=6_000)
    outbox = FakeOutbox()
    metadata = _family_metadata("inv-a", "inv-b")
    settled = _pi_event(
        "evt_ret_ok", "payment_intent.succeeded", "pi_ret", 16_000, metadata, ach=True
    )
    await _webhook(real_db, outbox).execute(settled, "test_signature")
    returned = _pi_event(
        "evt_ret",
        "payment_intent.payment_failed",
        "pi_ret",
        16_000,
        metadata,
        ach=True,
        last_payment_error={"code": "insufficient_funds"},
    )
    await _webhook(real_db, outbox).execute(returned, "test_signature")
    await _webhook(real_db, outbox).execute(returned, "test_signature")

    for invoice_id in ("inv-a", "inv-b"):
        assert (await _invoice(real_db, invoice_id))["status"] == "open"
    (notice,) = _notices(outbox)
    assert notice.payload.invoice_ids == ("inv-a", "inv-b")
    assert notice.payload.balance_due_cents == 16_000


async def test_overlapping_late_fee_passes_write_one_fee_per_family(real_db, acad) -> None:
    """Both siblings overdue; the family check is defeated (as two overlapping
    passes would each read "no fee yet"), so the store must refuse the second."""
    await _seed(real_db, "inv-a", due=date(2026, 6, 1))
    await _seed(real_db, "inv-b", due=date(2026, 6, 1))
    ledger = MongoBillingLedgerRepository(real_db)

    class _Fees:
        async def execute(self, academy_id: str) -> Any:
            return type("F", (), {"late_fee_cents": 1_500, "grace_days": 0})()

    passes = ApplyLateFees(
        ledger=ledger, add_line=AddInvoiceLine(ledger=ledger), fees=_Fees(), clock=lambda: NOW
    )

    async def _never_charged(_invoice: LedgerInvoice) -> bool:
        return False

    passes._family_already_charged = _never_charged  # type: ignore[method-assign]
    result = await passes.execute(academy_id=ACAD)

    assert (result.applied, result.skipped_existing) == (1, 1)
    fees = await real_db["invoice_lines"].find({"line_type": LATE_FEE_LINE_TYPE}).to_list(None)
    assert [(f["invoice_id"], f["source_id"]) for f in fees] == [("inv-a", f"{PARENT}:2026-06")]
    # The refused write left no fee in the sibling's totals.
    assert (await _invoice(real_db, "inv-b"))["balance_due_cents"] == 10_000
    assert (await _invoice(real_db, "inv-a"))["balance_due_cents"] == 11_500


async def test_the_family_check_skips_a_sibling_already_charged_this_month(real_db, acad) -> None:
    await _seed(real_db, "inv-a", due=date(2026, 6, 1))
    await _seed(real_db, "inv-b", due=date(2026, 6, 1))
    await _seed(real_db, "inv-next", due=date(2026, 6, 1), period="2026-05")
    ledger = MongoBillingLedgerRepository(real_db)

    class _Fees:
        async def execute(self, academy_id: str) -> Any:
            return type("F", (), {"late_fee_cents": 1_500, "grace_days": 0})()

    result = await ApplyLateFees(
        ledger=ledger, add_line=AddInvoiceLine(ledger=ledger), fees=_Fees(), clock=lambda: NOW
    ).execute(academy_id=ACAD)

    # One fee for June's two children, one for May: a month apart is two lateness.
    assert (result.applied, result.skipped_existing) == (2, 1)


async def test_reconciled_family_charge_is_labelled_autopay(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b")

    class _Gateway:
        async def search_app_owned_payment_intents(self, **_: Any) -> list[dict[str, Any]]:
            return [
                {
                    "id": "pi_rec",
                    "status": "succeeded",
                    "amount": 20_000,
                    "currency": "usd",
                    "metadata": _family_metadata("inv-a", "inv-b"),
                }
            ]

    reconciler = ReconcileStripePaymentIntents(
        stripe=_Gateway(),
        ledger=MongoBillingLedgerRepository(real_db),
        run_recorder=None,
        academy_id=ACAD,
        clock=lambda: NOW,
    )
    assert (await reconciler.execute())["repaired"] == 1

    payment = await real_db["ledger_payments"].find_one({"stripe_payment_intent_id": "pi_rec"})
    assert payment["payment_method"] == "stripe_autopay"
    assert await real_db["payment_allocations"].count_documents({"academy_id": ACAD}) == 2


async def test_a_large_family_splits_to_fit_stripes_metadata_cap(real_db, acad) -> None:
    """Stripe caps a metadata value at 500 chars: a family too big for one
    ``invoice_ids`` splits deterministically by invoice id across charges."""
    invoice_ids = [f"inv-monthly-enrollment-{n:02d}-padding-padding-2026-06" for n in range(12)]
    for invoice_id in invoice_ids:
        await _seed(real_db, invoice_id, cents=1_000)
    stripe = _Stripe()

    await _tick(real_db, stripe, FakeOutbox())

    charged = [i["metadata"]["invoice_ids"].split(",") for i in stripe.intents.values()]
    assert all(len(",".join(ids)) <= 500 for ids in charged)
    assert sorted(i for ids in charged for i in ids) == invoice_ids
    assert charged[0] == invoice_ids[: len(charged[0])]  # the first group is the lowest ids
    assert len(charged) == 2


@pytest.mark.parametrize("exc", [StripeUnavailable, RuntimeError])
async def test_family_retry_after_a_timeout_replays_the_first_charge(real_db, acad, exc) -> None:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b")
    stripe = _TimeoutStripe(exc)

    await _tick(real_db, stripe, FakeOutbox())
    await _tick(real_db, stripe, FakeOutbox(), at=NOW + timedelta(minutes=61))

    assert len(stripe.intents) == 1  # the retry replays the first key
    assert len({c["key"] for c in stripe.calls}) == 1
    for invoice_id in ("inv-a", "inv-b"):
        assert (await _invoice(real_db, invoice_id))["status"] == "paid"


@pytest.mark.parametrize("exc", [StripeUnavailable, RuntimeError])
async def test_single_retry_after_a_timeout_replays_the_first_charge(real_db, acad, exc) -> None:
    await _seed(real_db, "inv-a")
    stripe = _TimeoutStripe(exc)

    await _tick(real_db, stripe, FakeOutbox())
    await _tick(real_db, stripe, FakeOutbox(), at=NOW + timedelta(minutes=61))

    assert len(stripe.intents) == 1


async def test_a_partial_retry_of_a_family_charge_never_charges_the_rest(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b")
    repo = MongoDunningStateRepository(real_db)
    await repo.prepare_due_states(now=NOW, limit=100)
    lead = await repo.claim_next_due(now=NOW, worker_id="w1", charge_group_id="grp-x")
    assert lead is not None
    members = [
        lead,
        *await repo.claim_group_siblings(
            lead=lead[1], now=NOW, worker_id="w1", rejoin=False, period="2026-06"
        ),
    ]
    stripe = _Stripe(crash_once=True)
    with pytest.raises(RuntimeError):
        await _charge(real_db, stripe).execute_family(
            [invoice.invoice_id for invoice, _ in members],
            charge_group_id="grp-x",
            retry_scopes={
                invoice.invoice_id: f"dunning-attempt:{state.processing_attempt_no}"
                for invoice, state in members
            },
        )
    # The worker died; B is then paid at the front desk.
    ledger = MongoBillingLedgerRepository(real_db)
    desk = await ledger.record_payment(
        LedgerPayment(
            payment_id="desk-b",
            academy_id=ACAD,
            parent_id=PARENT,
            amount_cents=10_000,
            unapplied_amount_cents=10_000,
            currency="usd",
            status="succeeded",
            payment_method="cash",
            paid_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        ),
        idempotency_key="desk:b",
    )
    await ledger.allocate_payment(
        payment_id=desk.payment_id,
        invoice_id="inv-b",
        amount_cents=10_000,
        idempotency_key="desk-alloc:b",
    )

    await _tick(real_db, stripe, FakeOutbox(), at=NOW + timedelta(minutes=31))
    await _tick(real_db, stripe, FakeOutbox(), at=NOW + timedelta(minutes=91))

    assert len(stripe.intents) == 1  # A is never charged alone while the family PI is open
    state_a = await real_db["dunning_states"].find_one({"academy_id": ACAD, "invoice_id": "inv-a"})
    assert state_a is not None
    assert state_a["suppression_reason"] == "attempt_indeterminate"
    assert state_a["charge_group_id"] == "grp-x"


async def test_a_lone_charge_parked_after_a_timeout_never_joins_a_family(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    stripe = _TimeoutStripe(StripeUnavailable)
    await _tick(real_db, stripe, FakeOutbox())
    await _seed(real_db, "inv-b")

    await _tick(real_db, stripe, FakeOutbox(), at=NOW + timedelta(minutes=61))

    # A replays its own key; B is charged on its own, never with A under a new key.
    assert sorted(i["amount_cents"] for i in stripe.intents.values()) == [10_000, 10_000]
    assert all("invoice_ids" not in i["metadata"] for i in stripe.intents.values())


async def test_an_unallocated_family_refund_is_shared_across_its_invoices(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b")
    payment = LedgerPayment(
        payment_id="ledger-pay-autopay:pi_ref",
        academy_id=ACAD,
        parent_id=PARENT,
        amount_cents=20_000,
        unapplied_amount_cents=20_000,
        currency="usd",
        status="succeeded",
        payment_method="stripe_autopay",
        stripe_payment_intent_id="pi_ref",
        metadata=_family_metadata("inv-a", "inv-b"),
        paid_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )

    await _webhook(real_db, FakeOutbox())._sync_invoice_refunds_for_ledger_payment(
        pi_id="pi_ref", payment=payment, total_refunded_cents=20_000
    )

    for invoice_id in ("inv-a", "inv-b"):
        assert (await _invoice(real_db, invoice_id))["refunded_cents"] == 10_000
