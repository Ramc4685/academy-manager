"""Money on the Family record: what the Billing tab and the family list show.

Real ``mongod`` with every migration applied (``real_db``), so the 0132
validators and the allocation/ledger unique indexes are production's. Covers:

* one payment settling MANY invoices (PR #645: never ``find_one`` a payment's
  invoice): partial allocations leave the right balance on each invoice, on
  the payment, and on the family, and the family list (People CRM A3a) and the
  Billing tab agree on that family balance, including an invoice stored under
  the parent's alias;
* the payment's unapplied balance is the ceiling, sequentially and under
  concurrent allocation to two invoices (#518);
* a refund is visible on the Billing tab, attached to its invoice, and does
  not reopen the invoice balance; HOW MUCH was refunded shows per invoice,
  per payment, per refund event and in the family totals (#929), including a
  refund made in Stripe that left no audit row;
* the refund path runs in the request academy, not the boot academy (C4).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.application.family_billing import strip_owner_actions
from backend.v2.contexts.billing.domain.ledger import LedgerPayment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.family_billing_read_model import (
    MongoFamilyBillingReadModel,
)
from backend.v2.contexts.billing.infrastructure.family_money_read_model import (
    MongoFamilyMoneyReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.crm.infrastructure.family_index_read_model import (
    MongoFamilyIndexReadModel,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.interfaces.admin.families_views import AdminFamilyBillingView
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

ACAD = "acad-fam-a"
OTHER = "acad-fam-b"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
PAID_AT = datetime(2026, 9, 20, 14, 0, tzinfo=UTC)
PARENT = "u-fam-money"
ALIAS = "fb-fam-money"


def _dt(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def _billing_tab(db: Any) -> MongoFamilyBillingReadModel:
    return MongoFamilyBillingReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=MongoParentBillingCustomerRepository(db),
        credits=MongoCreditLedgerRepository(db),
        users=MongoUserRepository(db),
        audit=MongoBillingAuditLogRepository(db),
        clock=lambda: NOW,
    )


def _family_list(db: Any) -> MongoFamilyIndexReadModel:
    return MongoFamilyIndexReadModel(
        db,
        parents=MongoUserRepository(db),
        children=MongoStudentRepository(db),
        money=MongoFamilyMoneyReadModel(db),
        academy_timezone=academy_timezone_lookup(db),
        clock=lambda: NOW,
    )


def _invoice(
    academy_id: str, invoice_id: str, total: int, *, parent_id: str = PARENT, status: str = "open"
) -> dict[str, Any]:
    return {
        "invoice_id": invoice_id,
        "academy_id": academy_id,
        "parent_id": parent_id,
        "student_id": "stu-fam-1",
        "enrollment_id": "enr-fam-1",
        "period": "2026-09",
        "status": status,
        "subtotal_cents": total,
        "discount_cents": 0,
        "total_cents": total,
        "balance_due_cents": 0 if status == "paid" else total,
        "refunded_cents": 0,
        "currency": "usd",
        "due_date": _dt(date(2026, 10, 5)),
        "created_at": datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
    }


async def _seed_family(db: Any, academy_id: str = ACAD) -> None:
    await db["academies"].insert_one(
        {"academy_id": academy_id, "display_name": "Test Academy", "timezone": "America/Chicago"}
    )
    await db["users"].insert_one(
        {
            "user_id": PARENT,
            "firebase_uid": ALIAS,
            "academy_id": academy_id,
            "display_name": "Testparent Money",
            "email": "money-parent@example.test",
            "roles": ["parent"],
        }
    )
    await db["students"].insert_many(
        [
            {
                "academy_id": academy_id,
                "student_id": "stu-fam-1",
                "parent_id": PARENT,
                "full_name": "Testchild One",
                "display_name": "Testchild One",
                "status": "active",
            },
            # A second child stored under the parent's firebase uid (spec §1).
            {
                "academy_id": academy_id,
                "student_id": "stu-fam-2",
                "parent_id": ALIAS,
                "full_name": "Testchild Two",
                "display_name": "Testchild Two",
                "status": "active",
            },
        ]
    )


def _payment(payment_id: str, amount: int, academy_id: str = ACAD) -> LedgerPayment:
    return LedgerPayment(
        payment_id=payment_id,
        academy_id=academy_id,
        parent_id=PARENT,
        amount_cents=amount,
        unapplied_amount_cents=amount,
        status="succeeded",
        payment_method="card",
        paid_at=PAID_AT,
        currency="usd",
        created_at=PAID_AT,
        updated_at=PAID_AT,
    )


async def _doc(db: Any, collection: str, **filt: Any) -> dict[str, Any]:
    doc = await db[collection].find_one(filt, {"_id": 0})
    assert doc is not None, (collection, filt)
    return doc


# ------------------------------------------------------------ one payment, many invoices


async def test_one_payment_partially_settles_two_invoices_and_every_view_agrees(real_db) -> None:
    await _seed_family(real_db)
    await real_db["invoices"].insert_many(
        [
            _invoice(ACAD, "inv-fam-1", 6_000),
            _invoice(ACAD, "inv-fam-2", 7_000),
            # Unpaid, stored under the alias: must still count on both views.
            _invoice(ACAD, "inv-fam-3", 4_000, parent_id=ALIAS),
        ]
    )
    repo = MongoBillingLedgerRepository(real_db)
    with tenant_scope(ACAD):
        await repo.record_payment(_payment("pay-multi", 10_000), idempotency_key="pay-multi")
        await repo.allocate_payment(
            payment_id="pay-multi", invoice_id="inv-fam-1", amount_cents=5_000, idempotency_key="a1"
        )
        await repo.allocate_payment(
            payment_id="pay-multi", invoice_id="inv-fam-2", amount_cents=4_000, idempotency_key="a2"
        )
        inv1 = await _doc(real_db, "invoices", academy_id=ACAD, invoice_id="inv-fam-1")
        inv2 = await _doc(real_db, "invoices", academy_id=ACAD, invoice_id="inv-fam-2")
        pay = await _doc(real_db, "ledger_payments", academy_id=ACAD, payment_id="pay-multi")
        assert (inv1["balance_due_cents"], inv1["status"]) == (1_000, "partially_paid")
        assert (inv2["balance_due_cents"], inv2["status"]) == (3_000, "partially_paid")
        assert pay["unapplied_amount_cents"] == 1_000

        # Asking for more than is left spends only what is left (the payment is the ceiling).
        await repo.allocate_payment(
            payment_id="pay-multi", invoice_id="inv-fam-2", amount_cents=2_000, idempotency_key="a3"
        )
        inv2 = await _doc(real_db, "invoices", academy_id=ACAD, invoice_id="inv-fam-2")
        pay = await _doc(real_db, "ledger_payments", academy_id=ACAD, payment_id="pay-multi")
        assert inv2["balance_due_cents"] == 2_000
        assert pay["unapplied_amount_cents"] == 0
        assert pay.get("over_allocated_cents", 0) == 0
        allocated = [
            a["amount_cents"]
            async for a in real_db["payment_allocations"].find(
                {"academy_id": ACAD, "payment_id": "pay-multi"}
            )
        ]
        assert sum(allocated) == 10_000

        family_row = next(
            f for f in (await _family_list(real_db).build(ACAD)).families if f.family_id == PARENT
        )
        views = [await _billing_tab(real_db).build(opened) for opened in (PARENT, ALIAS)]

    # Family balance: 1,000 + 2,000 + 4,000 (the alias invoice), on BOTH views.
    assert family_row.money is not None
    assert family_row.money.balance_cents == 7_000
    assert family_row.money.open_invoice_count == 3
    for view in views:
        assert view is not None
        assert view["header"]["balance_cents"] == family_row.money.balance_cents
        assert view["header"]["open_invoice_count"] == family_row.money.open_invoice_count
        rows = {inv["invoice_id"]: inv for inv in view["invoices"]}
        assert rows["inv-fam-1"]["balance_due_cents"] == 1_000
        assert rows["inv-fam-2"]["balance_due_cents"] == 2_000
        assert rows["inv-fam-3"]["balance_due_cents"] == 4_000
        # The payment is listed against EVERY invoice it touched.
        assert [a["amount_cents"] for a in rows["inv-fam-1"]["allocations"]] == [5_000]
        assert sorted(a["amount_cents"] for a in rows["inv-fam-2"]["allocations"]) == [
            1_000,
            4_000,
        ]
        # One timeline entry for the one payment, naming both invoices and the full amount.
        received = [e for e in view["timeline"] if e["code"] == "payment_received"]
        assert len(received) == 1
        # Each invoice once, even though inv-fam-2 took two allocations.
        assert received[0]["invoice_ids"] == ["inv-fam-1", "inv-fam-2"]
        assert received[0]["amount_cents"] == 10_000
        last = view["header"]["last_payment"]
        assert last["amount_cents"] == 10_000
        assert sorted(last["invoice_ids"]) == ["inv-fam-1", "inv-fam-2"]


async def test_concurrent_allocations_never_spend_one_payment_twice(real_db) -> None:
    """#518 on a real server: two invoices race for the same 5,000."""
    await _seed_family(real_db)
    await real_db["invoices"].insert_many(
        [_invoice(ACAD, "inv-race-1", 5_000), _invoice(ACAD, "inv-race-2", 5_000)]
    )
    repo = MongoBillingLedgerRepository(real_db)
    with tenant_scope(ACAD):
        await repo.record_payment(_payment("pay-race", 5_000), idempotency_key="pay-race")
        results = await asyncio.gather(
            repo.allocate_payment(
                payment_id="pay-race",
                invoice_id="inv-race-1",
                amount_cents=5_000,
                idempotency_key="race-1",
            ),
            repo.allocate_payment(
                payment_id="pay-race",
                invoice_id="inv-race-2",
                amount_cents=5_000,
                idempotency_key="race-2",
            ),
            return_exceptions=True,
        )
        pay = await _doc(real_db, "ledger_payments", academy_id=ACAD, payment_id="pay-race")
        allocated = [
            a["amount_cents"]
            async for a in real_db["payment_allocations"].find(
                {"academy_id": ACAD, "payment_id": "pay-race"}
            )
        ]
        balances = [
            (await _doc(real_db, "invoices", academy_id=ACAD, invoice_id=i))["balance_due_cents"]
            for i in ("inv-race-1", "inv-race-2")
        ]

    assert sum(allocated) <= 5_000, (allocated, results)
    assert sum(5_000 - b for b in balances) == sum(allocated)
    assert pay["unapplied_amount_cents"] == 5_000 - sum(allocated)
    assert pay.get("over_allocated_cents", 0) == 0


# ------------------------------------------------------------ refunds


class _FakeOutbox:
    async def append(self, event: object) -> None:
        return None


@pytest.fixture
def boot_academy(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.delenv("V2_PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.delenv("PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.setenv("V2_DEFAULT_ACADEMY_ID", ACAD)
    monkeypatch.setenv("DEFAULT_ACADEMY_ID", ACAD)
    get_settings.cache_clear()
    yield ACAD
    get_settings.cache_clear()


async def _seed_card_payment(db: Any, academy_id: str) -> None:
    """A Stripe-settled invoice: the only kind the refund route can refund."""
    await db["invoices"].insert_one(_invoice(academy_id, "inv-refund", 6_000, status="paid"))
    await db["payments"].insert_one(
        {
            "payment_id": "pay-refund",
            "academy_id": academy_id,
            "parent_id": PARENT,
            "session_id": "sess-fam-1",
            "stripe_payment_intent_id": "pi_fam_refund",
            "amount_cents": 6_000,
            "currency": "usd",
            "status": "succeeded",
            "refunded_cents": 0,
            "created_at": PAID_AT,
            "updated_at": PAID_AT,
        }
    )
    await db["ledger_payments"].insert_one(
        {
            **_payment("pay-refund", 6_000, academy_id).model_dump(mode="python"),
            "unapplied_amount_cents": 0,
            "stripe_payment_intent_id": "pi_fam_refund",
        }
    )
    await db["payment_allocations"].insert_one(
        {
            "allocation_id": "alloc-refund",
            "academy_id": academy_id,
            "payment_id": "pay-refund",
            "invoice_id": "inv-refund",
            "amount_cents": 6_000,
            "created_at": PAID_AT,
        }
    )


def _admin(db: Any) -> Any:
    return compose_admin(
        db,
        outbox=_FakeOutbox(),  # type: ignore[arg-type]
        idempotency_store=MongoIdempotencyStore(db),
        stripe=FakeStripeGateway(),
    )


@pytest.mark.parametrize("academy_id", [ACAD, OTHER], ids=["boot-academy", "request-academy"])
async def test_refund_is_visible_on_the_billing_tab_of_its_own_academy(
    real_db, boot_academy, academy_id: str
) -> None:
    await _seed_family(real_db, academy_id)
    await _seed_card_payment(real_db, academy_id)
    admin = _admin(real_db)
    with tenant_scope(academy_id):
        result = await admin.issue_invoice_refund(
            invoice_id="inv-refund",
            amount_cents=2_500,
            reason="class cancelled",
            actor_id="owner-1",
        )
        view = await _billing_tab(real_db).build(PARENT)
        invoice = await _doc(real_db, "invoices", academy_id=academy_id, invoice_id="inv-refund")

    assert result["refunded_cents"] == 2_500
    assert invoice["refunded_cents"] == 2_500
    assert view is not None
    refunds = [e for e in view["timeline"] if e["code"] == "audit:refund_issued"]
    assert len(refunds) == 1
    assert refunds[0]["invoice_id"] == "inv-refund"
    assert refunds[0]["actor_id"] == "owner-1"
    assert "class cancelled" in refunds[0]["summary"]
    # A refund gives money back; it does not make the invoice owed again.
    row = next(inv for inv in view["invoices"] if inv["invoice_id"] == "inv-refund")
    assert row["balance_due_cents"] == 0
    assert view["header"]["balance_cents"] == 0
    # The other academy's trail is untouched.
    other = OTHER if academy_id == ACAD else ACAD
    assert await real_db["billing_audit_log"].count_documents({"academy_id": other}) == 0


def _payment_entry(view: dict[str, Any], payment_id: str) -> dict[str, Any]:
    return next(
        e for e in view["timeline"] if e["code"] == "payment_received" and e["reason"] == payment_id
    )


async def test_refunded_amount_is_visible_on_the_billing_tab(real_db, boot_academy) -> None:
    """#929: how much came back, per invoice, per payment and for the family."""
    await _seed_family(real_db)
    await _seed_card_payment(real_db, ACAD)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        await admin.issue_invoice_refund(
            invoice_id="inv-refund",
            amount_cents=2_500,
            reason="class cancelled",
            actor_id="owner-1",
        )
        view = await _billing_tab(real_db).build(PARENT)

    assert view is not None
    row = next(inv for inv in view["invoices"] if inv["invoice_id"] == "inv-refund")
    assert row["paid_cents"] == 6_000
    assert row["refunded_cents"] == 2_500
    assert row["net_paid_cents"] == 3_500
    # A refund gives money back; it does not reopen the balance.
    assert row["balance_due_cents"] == 0
    # 2,500 of the 6,000 is still refundable, so Refund stays on offer.
    assert "refund" in row["actions"]

    refund_entry = next(e for e in view["timeline"] if e["code"] == "audit:refund_issued")
    assert refund_entry["amount_cents"] == 2_500
    assert "$25" in refund_entry["summary"]

    # The payment itself: the refund is visible on the payment, not only the invoice.
    received = _payment_entry(view, "pay-refund")
    assert received["amount_cents"] == 6_000
    assert received["refunded_cents"] == 2_500
    last = view["header"]["last_payment"]
    assert (last["amount_cents"], last["refunded_cents"], last["net_cents"]) == (
        6_000,
        2_500,
        3_500,
    )

    # Family totals.
    header = view["header"]
    assert (header["paid_cents"], header["refunded_cents"], header["net_paid_cents"]) == (
        6_000,
        2_500,
        3_500,
    )
    assert header["balance_cents"] == 0


async def test_two_partial_refunds_each_show_their_own_amount(real_db, boot_academy) -> None:
    """The audit row's ``after`` is cumulative: each entry is the delta, not the running total."""
    await _seed_family(real_db)
    await _seed_card_payment(real_db, ACAD)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        await admin.issue_invoice_refund(
            invoice_id="inv-refund", amount_cents=1_000, reason="missed class", actor_id="owner-1"
        )
        await admin.issue_invoice_refund(
            invoice_id="inv-refund", amount_cents=1_500, reason="coach absent", actor_id="owner-1"
        )
        view = await _billing_tab(real_db).build(PARENT)

    assert view is not None
    refunds = {
        e["reason"]: e["amount_cents"]
        for e in view["timeline"]
        if e["code"] == "audit:refund_issued"
    }
    assert refunds == {"missed class": 1_000, "coach absent": 1_500}
    row = next(inv for inv in view["invoices"] if inv["invoice_id"] == "inv-refund")
    assert (row["refunded_cents"], row["net_paid_cents"]) == (2_500, 3_500)
    assert _payment_entry(view, "pay-refund")["refunded_cents"] == 2_500
    assert view["header"]["refunded_cents"] == 2_500


async def test_fully_refunded_invoice_offers_no_further_refund(real_db, boot_academy) -> None:
    await _seed_family(real_db)
    await _seed_card_payment(real_db, ACAD)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        await admin.issue_invoice_refund(
            invoice_id="inv-refund", amount_cents=6_000, reason="withdrew", actor_id="owner-1"
        )
        view = await _billing_tab(real_db).build(PARENT)

    assert view is not None
    row = next(inv for inv in view["invoices"] if inv["invoice_id"] == "inv-refund")
    assert (row["refunded_cents"], row["net_paid_cents"]) == (6_000, 0)
    assert "refund" not in row["actions"]
    assert view["header"]["net_paid_cents"] == 0


async def test_refund_made_in_stripe_without_an_audit_row_still_shows(real_db) -> None:
    """A Stripe-dashboard refund reaches Mongo through the webhook (invoice
    ``refunded_cents`` via ``apply_invoice_refund``, the ledger payment via
    ``mark_payment_refunded``) and writes no audit row. One ledger-only payment
    settles two invoices; the family totals add both invoices up."""
    await _seed_family(real_db)
    await real_db["invoices"].insert_many(
        [
            _invoice(ACAD, "inv-dash-1", 4_000, status="paid"),
            _invoice(ACAD, "inv-dash-2", 3_000, parent_id=ALIAS, status="paid"),
        ]
    )
    repo = MongoBillingLedgerRepository(real_db)
    with tenant_scope(ACAD):
        await repo.record_payment(
            _payment("pay-dash", 7_000).model_copy(
                update={"stripe_payment_intent_id": "pi_fam_dash"}
            ),
            idempotency_key="pay-dash",
        )
        await real_db["payment_allocations"].insert_many(
            [
                {
                    "allocation_id": "alloc-dash-1",
                    "academy_id": ACAD,
                    "payment_id": "pay-dash",
                    "invoice_id": "inv-dash-1",
                    "amount_cents": 4_000,
                    "created_at": PAID_AT,
                },
                {
                    "allocation_id": "alloc-dash-2",
                    "academy_id": ACAD,
                    "payment_id": "pay-dash",
                    "invoice_id": "inv-dash-2",
                    "amount_cents": 3_000,
                    "created_at": PAID_AT,
                },
            ]
        )
        await repo.apply_invoice_refund(invoice_id="inv-dash-1", amount_cents=4_000)
        await repo.apply_invoice_refund(invoice_id="inv-dash-2", amount_cents=1_000)
        await repo.mark_payment_refunded(
            "pay-dash", refunded_cents=5_000, status="partially_refunded", updated_at=NOW
        )
        view = await _billing_tab(real_db).build(PARENT)

    assert view is not None
    assert not [e for e in view["timeline"] if e["code"] == "audit:refund_issued"]
    rows = {inv["invoice_id"]: inv for inv in view["invoices"]}
    assert (rows["inv-dash-1"]["refunded_cents"], rows["inv-dash-1"]["net_paid_cents"]) == (
        4_000,
        0,
    )
    assert (rows["inv-dash-2"]["refunded_cents"], rows["inv-dash-2"]["net_paid_cents"]) == (
        1_000,
        2_000,
    )
    received = _payment_entry(view, "pay-dash")
    assert (received["amount_cents"], received["refunded_cents"]) == (7_000, 5_000)
    header = view["header"]
    assert (header["paid_cents"], header["refunded_cents"], header["net_paid_cents"]) == (
        7_000,
        5_000,
        2_000,
    )
    assert header["last_payment"]["net_cents"] == 2_000


async def test_refund_amounts_survive_the_response_model_for_non_owner_admins(
    real_db, boot_academy
) -> None:
    """The route validates through ``AdminFamilyBillingView`` (``extra="ignore"``)
    and strips owner-only ACTIONS for non-owners. Amounts are not an owner-only
    thing: billing staff see them (2026-09-22 staff-tier decision), and #553's
    front-desk tier is not built, so no amount is hidden here. Only the Refund
    button goes."""
    await _seed_family(real_db)
    await _seed_card_payment(real_db, ACAD)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        await admin.issue_invoice_refund(
            invoice_id="inv-refund", amount_cents=2_500, reason="class cancelled", actor_id="o-1"
        )
        view = await _billing_tab(real_db).build(PARENT)

    assert view is not None
    for shaped in (view, strip_owner_actions(view)):
        body = AdminFamilyBillingView.model_validate(shaped).model_dump()
        row = next(inv for inv in body["invoices"] if inv["invoice_id"] == "inv-refund")
        assert (row["refunded_cents"], row["net_paid_cents"]) == (2_500, 3_500)
        header = body["header"]
        assert (header["refunded_cents"], header["net_paid_cents"]) == (2_500, 3_500)
        assert header["last_payment"]["refunded_cents"] == 2_500
        entries = {e["code"]: e for e in body["timeline"]}
        assert entries["audit:refund_issued"]["amount_cents"] == 2_500
        assert entries["payment_received"]["refunded_cents"] == 2_500
    stripped = strip_owner_actions(view)
    row = next(inv for inv in stripped["invoices"] if inv["invoice_id"] == "inv-refund")
    assert "refund" not in row["actions"]
